
import json
import requests
from config import Config

Config.validate()

HEADERS = {
    "Authorization": f"Bearer {Config.HF_TOKEN}",
    "Content-Type": "application/json"
}

def evaluate_with_ai(test_questions, user_answers):
    """
    test_questions: list of dicts: {id, question, options, answer}
    user_answers: dict mapping id -> chosen_index
    Ask the model to grade and explain; expect JSON:
    {"score": X, "total": N, "details":[{"id":1,"correct":true,"explanation":"..."}]}
    """
    # Build assistant prompt containing questions, correct answers, and user's chosen options
    s = "Grade the candidate's answers. Return only JSON: {\"score\": int, \"total\": int, \"details\":[{...}]}\n\n"
    for q in test_questions:
        qid = q.get("id")
        s += f"Q{qid}: {q.get('question')}\n"
        for i, opt in enumerate(q.get("options", [])):
            s += f"  {i}. {opt}\n"
        correct = q.get("answer")
        chosen = user_answers.get(str(qid)) if str(qid) in user_answers else user_answers.get(qid)
        s += f"Correct answer index: {correct}\n"
        s += f"Candidate chose: {chosen}\n\n"

    payload = {
        "model": Config.MODEL,
        "messages": [
            {"role": "system", "content": "You are an objective grader. Output only JSON."},
            {"role": "user", "content": s}
        ],
        "max_tokens": 800,
        "temperature": 0.0
    }

    r = requests.post(Config.HF_API_URL, headers=HEADERS, json=payload, timeout=60)
    if r.status_code != 200:
        return {"error": r.text, "status_code": r.status_code}

    content = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    try:
        return json.loads(content)
    except Exception:
        # If model didn't produce exact JSON, return raw content for debugging
        return {"error": "Could not parse evaluator JSON", "raw": content}
