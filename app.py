import os
import uuid
import smtplib
import re
import json
import requests
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import unquote

from flask import Flask, render_template, request, jsonify, session, redirect
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson.objectid import ObjectId
from config import Config
from ai.hf_generator import generate_mcq
import cloudinary
import cloudinary.uploader


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "super_secret_key")
CORS(app)
cloudinary.config(
    cloud_name=Config.CLOUDINARY_CLOUD_NAME,
    api_key=Config.CLOUDINARY_API_KEY,
    api_secret=Config.CLOUDINARY_API_SECRET,
    secure=True
)

# -------------------------------
# MongoDB Atlas Connection
# -------------------------------
client = MongoClient(Config.MONGO_URI)
db = client[Config.MONGO_DB]

applications = db.applications
users = db.users
tests = db.tests
MCQ_QUESTION_COUNT = max(10, int(os.getenv("MCQ_QUESTION_COUNT", "12")))
VIRTUAL_QUESTION_COUNT = max(5, int(os.getenv("VIRTUAL_QUESTION_COUNT", "7")))


def parse_object_id(value):
    try:
        return ObjectId(value)
    except Exception:
        return None


def upload_resume_to_cloudinary(resume_file):
    if not (Config.CLOUDINARY_CLOUD_NAME and Config.CLOUDINARY_API_KEY and Config.CLOUDINARY_API_SECRET):
        return None, "Cloudinary credentials are not configured"

    original = secure_filename(resume_file.filename or "resume.pdf")
    base_name = os.path.splitext(original)[0] or "resume"
    public_id = f"{uuid.uuid4().hex}_{base_name}"

    try:
        result = cloudinary.uploader.upload(
            resume_file,
            resource_type="raw",
            folder=Config.CLOUDINARY_FOLDER,
            public_id=public_id,
            overwrite=False
        )
    except Exception as e:
        return None, f"Cloudinary upload failed: {str(e)}"

    resume_url = result.get("secure_url") or result.get("url")
    if not resume_url:
        return None, "Cloudinary response missing file URL"
    return resume_url, None


def send_email(to_email, subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = Config.SMTP_USER
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SMTP_USER, Config.SMTP_PASS)
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)


def extract_json_block(text):
    if not text:
        return None
    cleaned = text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    obj_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if obj_match:
        try:
            return json.loads(obj_match.group())
        except Exception:
            pass
    return None


def normalize_mcq_questions(raw_questions):
    normalized = []
    if not isinstance(raw_questions, list):
        return normalized

    for q in raw_questions:
        if not isinstance(q, dict):
            continue
        question_text = str(q.get("question", "")).strip()
        options = q.get("options")
        answer = q.get("answer")

        if not question_text:
            continue
        if not isinstance(options, list) or len(options) != 4:
            continue
        if not isinstance(answer, int) or answer < 0 or answer > 3:
            continue

        normalized.append({
            "question": question_text,
            "options": [str(opt).strip() for opt in options],
            "answer": answer
        })

    return normalized


def generate_mcq_questions_with_fallback(user, total_count):
    base_prompt = f"""
Generate high-quality, competitive, role-specific technical MCQ interview questions.

Candidate profile:
- Job role: {user.get('job_role')}
- Skills: {user.get('skills')}

Each question must:
- Be relevant to the job role and skills
- Have exactly 4 options
- Have one clearly correct answer index (0-3)
- Include a mix of fundamentals, practical scenarios, and debugging/problem-solving
- Avoid repetition and trivial questions
"""

    collected = []
    seen = set()
    last_error = None
    attempts = 0
    max_attempts = max(8, total_count)

    while len(collected) < total_count and attempts < max_attempts:
        attempts += 1
        remaining = total_count - len(collected)
        batch_size = min(8, remaining)
        recent_questions = "\n".join([f"- {q['question']}" for q in collected[-8:]]) or "- None yet"

        prompt = f"""
{base_prompt}

Generate exactly {batch_size} questions in this batch.
Do not repeat questions that are semantically similar to:
{recent_questions}
"""

        result = generate_mcq(prompt, batch_size)
        if not result:
            last_error = {"error": "Empty model response"}
            continue
        if isinstance(result, dict) and result.get("error"):
            last_error = result
            continue
        if not isinstance(result, dict) or "questions" not in result:
            last_error = {"error": "Invalid question format from AI", "details": result}
            continue

        parsed_batch = normalize_mcq_questions(result.get("questions"))
        if not parsed_batch:
            last_error = {"error": "No valid questions in generated batch"}
            continue

        for item in parsed_batch:
            dedupe_key = re.sub(r"\s+", " ", item["question"]).strip().lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            collected.append(item)
            if len(collected) >= total_count:
                break

    if len(collected) < total_count:
        return None, last_error or {"error": "Insufficient valid questions from AI"}

    final_questions = []
    for idx, q in enumerate(collected[:total_count], start=1):
        final_questions.append({
            "id": idx,
            "question": q["question"],
            "options": q["options"],
            "answer": q["answer"]
        })
    return final_questions, None


def query_ollama(prompt_text):
    payload = {
        "model": Config.OLLAMA_MODEL,
        "prompt": prompt_text,
        "stream": False
    }
    try:
        response = requests.post(Config.OLLAMA_URL, json=payload, timeout=120)
    except Exception as e:
        return None, {"provider": "ollama", "error": f"Request failed: {str(e)}"}

    if response.status_code != 200:
        return None, {"provider": "ollama", "status_code": response.status_code, "details": response.text}

    body = response.json()
    content = body.get("response")
    if not content:
        return None, {"provider": "ollama", "error": "Missing response field"}
    return content, None


def query_hf_chat(prompt_text, model_name, max_tokens=800):
    if not Config.HF_TOKEN:
        return None, {"provider": "hf", "error": "HF_TOKEN not configured"}
    headers = {
        "Authorization": f"Bearer {Config.HF_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are an interview question generator. Output JSON only."},
            {"role": "user", "content": prompt_text}
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens
    }
    try:
        response = requests.post(Config.HF_API_URL, headers=headers, json=payload, timeout=60)
    except Exception as e:
        return None, {"provider": "hf", "error": f"Request failed: {str(e)}"}

    if response.status_code != 200:
        return None, {"provider": "hf", "status_code": response.status_code, "details": response.text}

    result = response.json()
    try:
        content = result["choices"][0]["message"]["content"]
    except Exception:
        return None, {"provider": "hf", "error": "Invalid response format", "raw": result}
    return content, None


def query_hf_text(prompt_text, model_name, system_message="You are a helpful assistant.", max_tokens=250):
    if not Config.HF_TOKEN:
        return None, {"provider": "hf", "error": "HF_TOKEN not configured"}
    headers = {
        "Authorization": f"Bearer {Config.HF_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt_text}
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens
    }
    try:
        response = requests.post(Config.HF_API_URL, headers=headers, json=payload, timeout=60)
    except Exception as e:
        return None, {"provider": "hf", "error": f"Request failed: {str(e)}"}

    if response.status_code != 200:
        return None, {"provider": "hf", "status_code": response.status_code, "details": response.text}

    result = response.json()
    try:
        content = result["choices"][0]["message"]["content"]
    except Exception:
        return None, {"provider": "hf", "error": "Invalid response format", "raw": result}
    return str(content or "").strip(), None


def evaluate_virtual_submission_with_fallback(evaluation_prompt):
    models = []
    for model in [
        Config.VIRTUAL_HF_MODEL,
        Config.MODEL,
        getattr(Config, "MCQ_SECONDARY_MODEL", None),
        getattr(Config, "MCQ_TERTIARY_MODEL", None)
    ]:
        if model and model not in models:
            models.append(model)

    errors = []
    for model in models:
        content, err = query_hf_text(
            evaluation_prompt,
            model,
            system_message="You are an interview evaluator. Return valid JSON only with score and feedback.",
            max_tokens=500
        )
        if not content:
            errors.append({"model": model, "error": err})
            continue

        parsed = extract_json_block(content)
        if isinstance(parsed, dict):
            return parsed, {"source": "hf", "model": model}

        number_match = re.search(r"\d+(\.\d+)?", content or "")
        if number_match:
            try:
                score_val = float(number_match.group())
            except Exception:
                score_val = 5.0
            return {
                "score": score_val,
                "feedback": "Virtual interview completed. Detailed structured feedback unavailable."
            }, {"source": "hf", "model": model, "format": "text_fallback"}

        errors.append({
            "model": model,
            "error": "Invalid evaluator response format",
            "raw_output": str(content)[:600]
        })

    return None, {"source": "local", "errors": errors}


def local_virtual_scoring(questions, answers):
    cleaned_answers = [str(a or "").strip() for a in answers]
    answered = [a for a in cleaned_answers if a]
    total = max(1, len(questions) if isinstance(questions, list) and questions else len(cleaned_answers))
    answered_count = len(answered)

    if answered_count == 0:
        return 0.0, "Interview was submitted without valid answers. Score reflects unanswered responses."

    avg_words = sum(len(a.split()) for a in answered) / answered_count
    completeness = answered_count / total
    depth = min(1.0, avg_words / 55.0)
    score = round((completeness * 6.0) + (depth * 4.0), 1)
    score = max(0.0, min(10.0, score))

    feedback = (
        f"You answered {answered_count} out of {total} questions. "
        f"Provide more detailed, structured examples to improve interview score."
    )
    return score, feedback


def _did_auth_header_value():
    if not Config.DID_API_KEY:
        return None
    token = Config.DID_API_KEY.strip()
    if token.lower().startswith("basic "):
        return token
    return f"Basic {token}"


def generate_did_talk_video(question_text):
    auth_value = _did_auth_header_value()
    if not auth_value:
        return None, {"error": "DID_API_KEY not configured"}

    headers = {
        "Authorization": auth_value,
        "Content-Type": "application/json"
    }

    create_payload = {
        "source_url": Config.DID_AVATAR_SOURCE_URL,
        "script": {
            "type": "text",
            "input": question_text,
            "provider": {
                "type": Config.DID_VOICE_PROVIDER,
                "voice_id": Config.DID_VOICE_ID
            }
        },
        "config": {
            "fluent": True
        }
    }

    talks_url = f"{Config.DID_BASE_URL.rstrip('/')}/talks"
    try:
        created = requests.post(talks_url, headers=headers, json=create_payload, timeout=60)
    except Exception as e:
        return None, {"error": f"D-ID create request failed: {str(e)}"}

    if created.status_code not in (200, 201):
        return None, {
            "error": "D-ID create talk failed",
            "status_code": created.status_code,
            "details": created.text
        }

    created_body = created.json()
    talk_id = created_body.get("id")
    result_url = created_body.get("result_url")
    if result_url:
        return result_url, None
    if not talk_id:
        return None, {"error": "D-ID create response missing talk id", "raw": created_body}

    # Poll until the talk video is ready.
    status_url = f"{talks_url}/{talk_id}"
    timeout_seconds = max(10, int(Config.DID_TALK_TIMEOUT_SECONDS))
    elapsed = 0
    while elapsed < timeout_seconds:
        try:
            status_resp = requests.get(status_url, headers=headers, timeout=30)
        except Exception as e:
            return None, {"error": f"D-ID poll request failed: {str(e)}"}

        if status_resp.status_code != 200:
            return None, {
                "error": "D-ID poll failed",
                "status_code": status_resp.status_code,
                "details": status_resp.text
            }

        body = status_resp.json()
        status = str(body.get("status", "")).lower()
        if status == "done" and body.get("result_url"):
            return body["result_url"], None
        if status in ("error", "failed"):
            return None, {"error": "D-ID talk generation failed", "raw": body}

        # Wait and retry.
        import time
        time.sleep(2)
        elapsed += 2

    return None, {"error": "D-ID talk timed out", "talk_id": talk_id}

# -------------------------------
# MAIN PAGE
# -------------------------------
@app.route("/")
def home():
    return render_template("main.html")

# -------------------------------
# APPLY
# -------------------------------
@app.route("/api/apply", methods=["POST"])
def apply():
    data = request.form
    resume = request.files.get("resume")

    if not resume or not resume.filename:
        return jsonify({"error": "Resume file is required"}), 400
    if not str(resume.filename).lower().endswith(".pdf"):
        return jsonify({"error": "Resume must be PDF"}), 400

    required_fields = ["first_name", "last_name", "email", "phone", "skills", "job_role"]
    for field in required_fields:
        if not str(data.get(field, "")).strip():
            return jsonify({"error": f"{field.replace('_', ' ').title()} is required"}), 400

    resume_url, upload_error = upload_resume_to_cloudinary(resume)
    if not resume_url:
        return jsonify({"error": "Resume upload failed", "details": upload_error}), 500

    applications.insert_one({
        "first_name": data.get("first_name"),
        "last_name": data.get("last_name"),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "skills": data.get("skills"),
        "job_role": data.get("job_role"),
        "resume": resume_url,
        "status": "pending",
        "created_at": datetime.utcnow()
    })

    return jsonify({"message": "Application submitted successfully"})

# -------------------------------
# HR LOGIN
# -------------------------------
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json() or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    if username == Config.ADMIN_USER and password == Config.ADMIN_PASS:
        session["admin"] = True
        return jsonify({"message": "Login success"})
    return jsonify({"error": "Invalid credentials"}), 401

# -------------------------------
# GET APPLICATIONS BY STATUS
# -------------------------------
@app.route("/api/admin/applications")
def get_applications():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 403

    pending = list(applications.find({"status": "pending"}))
    rejected = list(applications.find({"status": "rejected"}))
    selected = list(users.find())

    for c in pending:
        c["_id"] = str(c["_id"])
    for c in rejected:
        c["_id"] = str(c["_id"])
    for c in selected:
        c["_id"] = str(c["_id"])

    return jsonify({
        "pending": pending,
        "rejected": rejected,
        "selected": selected
    })

# -------------------------------
# ACCEPT APPLICATION
# -------------------------------
@app.route("/api/admin/accept/<id>", methods=["POST"])
def accept_candidate(id):
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 403

    object_id = parse_object_id(id)
    if not object_id:
        return jsonify({"error": "Invalid candidate id"}), 400

    app_data = applications.find_one({"_id": object_id})
    if not app_data:
        return jsonify({"error": "Application not found"}), 404

    username = f"{app_data['first_name'].lower()}.{uuid.uuid4().hex[:4]}"
   
    raw_password = uuid.uuid4().hex[:8]


    users.insert_one({
    "application_id": str(app_data["_id"]),
    "first_name": app_data["first_name"],
    "last_name": app_data["last_name"],
    "email": app_data["email"],
    "phone": app_data["phone"],
    "skills": app_data["skills"],
    "job_role": app_data["job_role"],
    "resume": app_data["resume"],   # important
    "username": username.lower(),
    "password": generate_password_hash(raw_password),
    "interview_taken": False,
    "score": None,
    "status": "selected",

    # NEW FIELDS FOR VIRTUAL ROUND
    "virtual_round_enabled": False,
    "virtual_taken": False,
    "virtual_score": None,
    "virtual_questions": [],
    "virtual_answers": [],
    "virtual_decision": "pending",
    "virtual_feedback": None,
    "virtual_duration_seconds": None,
    "mcq_completed_at": None,
    "updated_at": datetime.utcnow()
})



    applications.update_one(
        {"_id": object_id},
        {"$set": {"status": "selected"}}
    )

    sent, email_error = send_email(
        app_data["email"],
        "SimuHire Interview Credentials",
        f"""
Hello {app_data['first_name']},

Congratulations! You are selected for SimuHire interview.

Username: {username}
Password: {raw_password}

Login at: http://127.0.0.1:5000

Regards,
SimuHire HR
"""
    )

    if sent:
        return jsonify({"message": "Candidate accepted and credentials sent"})
    return jsonify({"message": "Candidate accepted but email failed", "email_error": email_error}), 200

@app.route("/resume/<path:resume_ref>")
def get_resume(resume_ref):
    decoded = unquote(resume_ref or "").strip()
    if decoded.startswith("http://") or decoded.startswith("https://"):
        return redirect(decoded)
    return jsonify({"error": "Resume link is invalid"}), 404

# -------------------------------
# REJECT
# -------------------------------
@app.route("/api/admin/reject/<id>", methods=["POST"])
def reject_candidate(id):
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 403

    object_id = parse_object_id(id)
    if not object_id:
        return jsonify({"error": "Invalid candidate id"}), 400

    applications.update_one(
        {"_id": object_id},
        {"$set": {"status": "rejected"}}
    )
    return jsonify({"message": "Rejected"})


@app.route("/api/admin/enable_virtual/<id>", methods=["POST"])
def enable_virtual(id):
    # Backward-compatible alias for promote API.
    return promote_virtual(id)


@app.route("/api/admin/virtual/promote/<id>", methods=["POST"])
def promote_virtual(id):

    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 403

    object_id = parse_object_id(id)
    if not object_id:
        return jsonify({"error": "Invalid candidate id"}), 400

    user = users.find_one({"_id": object_id})
    if not user:
        return jsonify({"error": "User not found"}), 404

    if not user.get("interview_taken"):
        return jsonify({"error": "Candidate has not completed MCQ interview yet"}), 400

    users.update_one(
        {"_id": object_id},
        {"$set": {
            "virtual_round_enabled": True,
            "virtual_decision": "promoted",
            "status": "selected",
            "updated_at": datetime.utcnow()
        }}
    )

    sent, email_error = send_email(
        user["email"],
        "SimuHire Virtual Interview Round",
        f"""
Hello {user['first_name']},

Congratulations! You are shortlisted for the AI Avatar Virtual Interview Round.

Please login to your dashboard and complete your 3-5 minute virtual interview.

Regards,
SimuHire HR
"""
    )

    if sent:
        return jsonify({"message": "Candidate promoted to virtual round and email sent"})
    return jsonify({"message": "Candidate promoted, but email failed", "email_error": email_error}), 200


@app.route("/api/admin/virtual/reject/<id>", methods=["POST"])
def reject_after_mcq(id):

    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 403

    object_id = parse_object_id(id)
    if not object_id:
        return jsonify({"error": "Invalid candidate id"}), 400

    user = users.find_one({"_id": object_id})
    if not user:
        return jsonify({"error": "User not found"}), 404

    users.update_one(
        {"_id": object_id},
        {"$set": {
            "virtual_round_enabled": False,
            "virtual_decision": "rejected",
            "status": "rejected",
            "updated_at": datetime.utcnow()
        }}
    )

    sent, email_error = send_email(
        user["email"],
        "SimuHire Interview Update",
        f"""
Hello {user['first_name']},

Thank you for completing the interview process.
We will get back to you.

Regards,
SimuHire HR
"""
    )

    if sent:
        return jsonify({"message": "Candidate removed from process and email sent"})
    return jsonify({"message": "Candidate removed, but email failed", "email_error": email_error}), 200

@app.route("/api/virtual/questions", methods=["POST"])
def generate_virtual_questions():

    if not session.get("candidate_id"):
        return jsonify({"error": "Unauthorized"}), 403

    user = users.find_one({"_id": ObjectId(session["candidate_id"])})
    if not user:
        return jsonify({"error": "Candidate not found"}), 404
    if not user.get("interview_taken"):
        return jsonify({"error": "Complete MCQ interview first"}), 400
    if not user.get("virtual_round_enabled"):
        return jsonify({"error": "Virtual round is not enabled by HR"}), 400
    if user.get("virtual_taken"):
        return jsonify({"error": "Virtual interview already completed"}), 400

    prompt = f"""
Generate exactly {VIRTUAL_QUESTION_COUNT} high-quality virtual interview questions for this candidate.
Candidate skills: {user.get('skills')}
Candidate role: {user.get('job_role')}

Question quality rules:
- Include practical, scenario-based and behavioral questions.
- Test depth, communication, and problem-solving.
- Avoid duplicate or generic questions.
- Keep each question concise and interview-ready.

Return ONLY valid JSON with this exact format:
{{
  "questions": [
    "Question 1",
    "Question 2",
    "Question 3",
    "Question 4",
    "Question 5"
  ]
}}
"""

    questions = None
    last_error = None
    preferred_provider = "ollama" if Config.USE_LOCAL_VIRTUAL_MODEL else "hf"
    fallback_provider = "hf" if preferred_provider == "ollama" else None

    for _ in range(3):
        content, err = (None, None)
        if preferred_provider == "ollama":
            content, err = query_ollama(prompt)
        else:
            content, err = query_hf_chat(prompt, Config.VIRTUAL_HF_MODEL, max_tokens=800)

        if not content and fallback_provider == "hf":
            content, fallback_err = query_hf_chat(prompt, Config.VIRTUAL_HF_MODEL, max_tokens=800)
            if content:
                err = None
            else:
                err = {"preferred_error": err, "fallback_error": fallback_err}

        if not content:
            last_error = err
            continue

        parsed = extract_json_block(content)
        if isinstance(parsed, dict) and isinstance(parsed.get("questions"), list):
            candidate_questions = [str(q).strip() for q in parsed["questions"] if str(q).strip()]
        else:
            candidate_questions = []
            for line in str(content).splitlines():
                cleaned = re.sub(r"^\s*(\d+[\).\-\s]+|[-*]\s+)", "", line).strip()
                if cleaned:
                    candidate_questions.append(cleaned)

        if len(candidate_questions) >= VIRTUAL_QUESTION_COUNT:
            questions = candidate_questions[:VIRTUAL_QUESTION_COUNT]
            break

        last_error = {"error": "AI returned insufficient virtual questions", "raw_output": content[:2000]}

    if not questions:
        return jsonify({"error": "Failed to generate virtual interview questions", "details": last_error}), 500

    users.update_one(
        {"_id": ObjectId(session["candidate_id"])},
        {"$set": {"virtual_questions": questions, "updated_at": datetime.utcnow()}}
    )

    return jsonify({
        "questions": questions,
        "total_questions": len(questions)
    })


@app.route("/api/virtual/avatar_question", methods=["POST"])
def generate_virtual_avatar_question():

    if not session.get("candidate_id"):
        return jsonify({"error": "Unauthorized"}), 403

    user = users.find_one({"_id": ObjectId(session["candidate_id"])})
    if not user:
        return jsonify({"error": "Candidate not found"}), 404
    if not user.get("interview_taken"):
        return jsonify({"error": "Complete MCQ interview first"}), 400
    if not user.get("virtual_round_enabled"):
        return jsonify({"error": "Virtual round is not enabled by HR"}), 400
    if user.get("virtual_taken"):
        return jsonify({"error": "Virtual interview already completed"}), 400

    data = request.get_json() or {}
    question = str(data.get("question", "")).strip()
    if not question:
        return jsonify({"error": "Question text is required"}), 400
    allowed_questions = [str(q).strip() for q in user.get("virtual_questions", [])]
    if allowed_questions and question not in allowed_questions:
        return jsonify({"error": "Question is not part of this interview session"}), 400

    video_url, err = generate_did_talk_video(question)
    if not video_url:
        return jsonify({"error": "Failed to generate avatar video", "details": err}), 500

    return jsonify({"video_url": video_url})


@app.route("/api/virtual/respond", methods=["POST"])
def virtual_interviewer_response():

    if not session.get("candidate_id"):
        return jsonify({"error": "Unauthorized"}), 403

    user = users.find_one({"_id": ObjectId(session["candidate_id"])})
    if not user:
        return jsonify({"error": "Candidate not found"}), 404
    if not user.get("virtual_round_enabled"):
        return jsonify({"error": "Virtual round is not enabled"}), 400
    if user.get("virtual_taken"):
        return jsonify({"error": "Virtual interview already submitted"}), 400

    data = request.get_json() or {}
    question = str(data.get("question", "")).strip()
    answer = str(data.get("answer", "")).strip()
    if not question or not answer:
        return jsonify({"error": "Question and answer are required"}), 400

    prompt = f"""
You are an HR interviewer in a virtual interview.
Question asked: {question}
Candidate answer: {answer}

Return a short spoken response in 1-2 sentences:
- acknowledge the answer
- give brief constructive feedback
- keep it professional and concise
Do not use markdown.
"""

    preferred_provider = "ollama" if Config.USE_LOCAL_VIRTUAL_MODEL else "hf"
    response_text = None
    last_error = None
    for _ in range(2):
        if preferred_provider == "ollama":
            response_text, err = query_ollama(prompt)
            if not response_text:
                fallback_text, fallback_err = query_hf_text(
                    prompt,
                    Config.VIRTUAL_HF_MODEL,
                    system_message="You are a professional HR interviewer.",
                    max_tokens=200
                )
                if fallback_text:
                    response_text = fallback_text
                    err = None
                else:
                    err = {"preferred_error": err, "fallback_error": fallback_err}
        else:
            response_text, err = query_hf_text(
                prompt,
                Config.VIRTUAL_HF_MODEL,
                system_message="You are a professional HR interviewer.",
                max_tokens=200
            )
        if response_text:
            break
        last_error = err

    if not response_text:
        return jsonify({"error": "Failed to generate interviewer response", "details": last_error}), 500

    cleaned = str(response_text).replace("```", "").strip()
    return jsonify({"response_text": cleaned[:500]})


@app.route("/api/virtual/submit", methods=["POST"])
def submit_virtual():

    if not session.get("candidate_id"):
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json() or {}
    answers = data.get("answers", [])
    duration_seconds = int(data.get("duration_seconds", 0))
    proctoring_violations = int(data.get("proctoring_violations", 0) or 0)
    auto_submitted = bool(data.get("auto_submitted", False))

    user = users.find_one({"_id": ObjectId(session["candidate_id"])})
    if not user:
        return jsonify({"error": "Candidate not found"}), 404
    if not user.get("virtual_round_enabled"):
        return jsonify({"error": "Virtual round is not enabled"}), 400
    if user.get("virtual_taken"):
        return jsonify({"error": "Virtual interview already submitted"}), 400

    if not isinstance(answers, list):
        return jsonify({"error": "Virtual answers format is invalid"}), 400

    questions = [str(q or "").strip() for q in user.get("virtual_questions", []) if str(q or "").strip()]
    normalized_answers = [str(a or "").strip() for a in answers]
    if questions and len(normalized_answers) < len(questions):
        normalized_answers.extend([""] * (len(questions) - len(normalized_answers)))
    if not normalized_answers:
        normalized_answers = [""] * (len(questions) if questions else 1)
    answered_count = sum(1 for a in normalized_answers if a)

    evaluation_prompt = f"""
Evaluate the candidate's answers for the following interview questions.
Provide:
1) Overall score out of 10
2) One short feedback paragraph

Questions: {questions}
Answers: {normalized_answers}

Important:
- Evaluate based on answered responses only.
- Ignore unanswered/empty responses while scoring.
- Keep scoring strict and interview-grade.

Return ONLY valid JSON:
{{
  "score": 0,
  "feedback": "short feedback text"
}}
"""

    score = 0.0
    feedback = "Virtual interview completed."
    evaluation_meta = {"source": "local"}
    evaluator_error = None

    if answered_count > 0:
        parsed, meta = evaluate_virtual_submission_with_fallback(evaluation_prompt)
        if isinstance(parsed, dict):
            raw_score = parsed.get("score", 5)
            try:
                score = float(raw_score)
            except Exception:
                score = 5.0
            feedback = str(parsed.get("feedback", feedback)).strip() or feedback
            evaluation_meta = meta or evaluation_meta
        else:
            score, feedback = local_virtual_scoring(questions, normalized_answers)
            evaluation_meta = meta or evaluation_meta
            evaluator_error = meta.get("errors") if isinstance(meta, dict) else None
    else:
        score, feedback = local_virtual_scoring(questions, normalized_answers)
        if auto_submitted:
            feedback = "Virtual interview was auto-submitted due to proctoring policy. " + feedback

    score = max(0.0, min(10.0, round(score, 1)))

    users.update_one(
        {"_id": ObjectId(session["candidate_id"])},
        {"$set": {
            "virtual_taken": True,
            "virtual_score": score,
            "virtual_answers": normalized_answers,
            "virtual_feedback": feedback,
            "virtual_duration_seconds": max(0, duration_seconds),
            "virtual_proctoring_violations": max(0, proctoring_violations),
            "virtual_answered_count": answered_count,
            "virtual_evaluation_source": evaluation_meta.get("source"),
            "virtual_evaluation_model": evaluation_meta.get("model"),
            "virtual_evaluation_error": evaluator_error,
            "virtual_completed_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }}
    )

    return jsonify({
        "message": "Virtual interview submitted",
        "score": score,
        "feedback": feedback
    })


# -------------------------------
# CANDIDATE LOGIN
# -------------------------------
@app.route("/api/candidate/login", methods=["POST"])
def candidate_login():
    data = request.get_json() or {}

    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", "")).strip()
    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    user = users.find_one({"username": username})

    if not user:
        return jsonify({"error": "Invalid username"}), 401

    if not check_password_hash(user["password"], password):
        return jsonify({"error": "Invalid password"}), 401

    session["candidate_id"] = str(user["_id"])

    return jsonify({
        "message": "Login successful",
        "interview_taken": user.get("interview_taken", False),
        "score": user.get("score"),
        "mcq_total_questions": user.get("mcq_total_questions", MCQ_QUESTION_COUNT),
        "status": user.get("status"),
        "virtual_round_enabled": user.get("virtual_round_enabled", False),
        "virtual_taken": user.get("virtual_taken", False),
        "virtual_decision": user.get("virtual_decision", "pending"),
        "virtual_score": user.get("virtual_score"),
        "virtual_feedback": user.get("virtual_feedback"),
        "virtual_question_count": len(user.get("virtual_questions", [])) if isinstance(user.get("virtual_questions"), list) else VIRTUAL_QUESTION_COUNT
    })


# -------------------------------
# START TEST
# -------------------------------
@app.route("/api/start_test", methods=["POST"])
def start_test():

    if not session.get("candidate_id"):
        return jsonify({"error": "Unauthorized"}), 403

    user = users.find_one({"_id": ObjectId(session["candidate_id"])})
    if not user:
        return jsonify({"error": "Candidate not found"}), 404
    if user.get("status") == "rejected":
        return jsonify({"error": "Your candidature is currently on hold. We will get back to you."}), 403

    if user.get("interview_taken"):
        return jsonify({"error": "Interview already taken"}), 400

    try:
        questions_data, last_error = generate_mcq_questions_with_fallback(user, MCQ_QUESTION_COUNT)
    except Exception as e:
        print("START TEST ERROR:", str(e))
        return jsonify({"error": "MCQ generation failed"}), 500

    if not questions_data:
        print("MCQ GENERATION ERROR:", last_error)
        return jsonify({"error": f"Could not generate {MCQ_QUESTION_COUNT} valid interview questions", "details": last_error}), 500

    test_id = str(uuid.uuid4())

    tests.insert_one({
        "test_id": test_id,
        "user_id": session["candidate_id"],
        "questions": questions_data
    })

    questions = [
        {
            "id": q["id"],
            "question": q["question"],
            "options": q["options"]
        }
        for q in questions_data
    ]

    return jsonify({
        "test_id": test_id,
        "questions": questions,
        "total_questions": len(questions)
    })


# -------------------------------
# SUBMIT TEST
# -------------------------------
@app.route("/api/submit_test", methods=["POST"])
def submit_test():

    if not session.get("candidate_id"):
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json() or {}
    test_id = str(data.get("test_id", "")).strip()
    answers = data.get("answers", [])
    if not test_id:
        return jsonify({"error": "test_id is required"}), 400
    if not isinstance(answers, list):
        return jsonify({"error": "answers must be a list"}), 400

    test = tests.find_one({"test_id": test_id})
    if not test:
        return jsonify({"error": "Invalid test session"}), 400

    score_raw = 0
    total_questions = len(test.get("questions", []))
    proctoring_violations = int(data.get("proctoring_violations", 0) or 0)

    for q in test["questions"]:
        for ans in answers:
            if ans["id"] == q["id"] and ans["answer"] == q["answer"]:
                score_raw += 1

    score = round((score_raw / total_questions) * 10, 1) if total_questions else 0.0

    users.update_one(
    {"_id": ObjectId(session["candidate_id"])},
    {"$set":{
        "interview_taken":True,
        "score":score,
        "mcq_raw_score": score_raw,
        "mcq_total_questions": total_questions,
        "mcq_proctoring_violations": max(0, proctoring_violations),
        "candidate_answers": answers,
        "questions_data": test["questions"],
        "mcq_completed_at": datetime.utcnow(),
        "virtual_round_enabled": False,
        "virtual_taken": False,
        "virtual_score": None,
        "virtual_questions": [],
        "virtual_answers": [],
        "virtual_feedback": None,
        "virtual_duration_seconds": None,
        "virtual_decision": "pending",
        "updated_at": datetime.utcnow()
    }}
)

    return jsonify({
        "score": score,
        "raw_score": score_raw,
        "total_questions": total_questions
    })

@app.route("/api/logout")
def logout():
    session.clear()
    return jsonify({"message":"Logged out"})


@app.route("/api/session/status")
def session_status():
    is_admin = bool(session.get("admin"))
    candidate_id = session.get("candidate_id")
    role = None
    candidate_state = {}

    if is_admin:
        role = "hr"
    elif candidate_id:
        role = "candidate"
        try:
            user = users.find_one({"_id": ObjectId(candidate_id)})
        except Exception:
            user = None
        if user:
            candidate_state = {
                "interview_taken": bool(user.get("interview_taken", False)),
                "virtual_round_enabled": bool(user.get("virtual_round_enabled", False)),
                "virtual_taken": bool(user.get("virtual_taken", False))
            }

    return jsonify({
        "logged_in": bool(role),
        "role": role,
        "candidate_state": candidate_state
    })

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")

