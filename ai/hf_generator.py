
import json
import re
import requests
import time
from config import Config

def _headers():
    return {
        "Authorization": f"Bearer {Config.HF_TOKEN}",
        "Content-Type": "application/json"
    }


def _extract_json(text):
    """
    Safely extract JSON from model output.
    Handles:
    - Markdown ```json blocks
    - Extra explanations
    - Text before/after JSON
    """

    text = text.strip()

    # Remove markdown code blocks
    text = re.sub(r"```json", "", text)
    text = re.sub(r"```", "", text).strip()

    # Try direct JSON parsing
    try:
        return json.loads(text)
    except:
        pass

    # Try extracting first JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass

    # Try extracting first JSON array
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass

    return None


def generate_mcq(prompt_text, num_questions=10, model_name=None, fallback_model_name=None):
    """
    Generate strictly formatted MCQ questions.
    Model must return:
    {
      "questions": [
        {
          "id": 1,
          "question": "...",
          "options": ["A", "B", "C", "D"],
          "answer": 0
        }
      ]
    }
    """

    if not Config.HF_TOKEN:
        return {"error": "HF_TOKEN is not configured"}

    system_message = (
        "You are a professional AI interview question generator. "
        "Return strictly valid JSON only. Do not add explanation. "
        "Do not add markdown. Do not add extra text."
    )

    user_message = f"""
{prompt_text}

Generate exactly {num_questions} multiple choice interview questions.

STRICT RULES:
- Return ONLY valid JSON.
- Do NOT include markdown.
- Do NOT include explanation.
- Do NOT include text before or after JSON.
- Each question must have exactly 4 options.
- 'answer' must be the correct option index (0-3).

JSON FORMAT:

{{
  "questions": [
    {{
      "id": 1,
      "question": "Question text",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "answer": 0
    }}
  ]
}}
"""

    primary_model = model_name or Config.MODEL
    secondary_model = fallback_model_name or Config.MCQ_SECONDARY_MODEL
    tertiary_model = Config.MCQ_TERTIARY_MODEL

    model_sequence = [primary_model]
    if secondary_model and secondary_model != primary_model:
        model_sequence.append(secondary_model)
    if tertiary_model and tertiary_model not in model_sequence:
        model_sequence.append(tertiary_model)

    payload_base = {
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ],
        "max_tokens": 1600,
        "temperature": 0.2   # Lower temperature = more structured output
    }
    model_errors = []

    for active_model in model_sequence:
        payload = dict(payload_base)
        payload["model"] = active_model

        response = None
        last_exception = None
        for attempt in range(3):
            try:
                response = requests.post(
                    Config.HF_API_URL,
                    headers=_headers(),
                    json=payload,
                    timeout=60
                )
                if response.status_code == 200:
                    break
                # Retry transient provider errors.
                if response.status_code in (408, 409, 429, 500, 502, 503, 504):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                model_errors.append({
                    "model": active_model,
                    "error": "HF API Error",
                    "status_code": response.status_code,
                    "details": response.text
                })
                response = None
                break
            except Exception as e:
                last_exception = e
                time.sleep(1.0 * (attempt + 1))

        if response is None:
            if last_exception is not None:
                model_errors.append({
                    "model": active_model,
                    "error": f"Request failed: {str(last_exception)}"
                })
            continue

        if response.status_code != 200:
            model_errors.append({
                "model": active_model,
                "error": "HF API Error",
                "status_code": response.status_code,
                "details": response.text
            })
            continue

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except Exception:
            model_errors.append({
                "model": active_model,
                "error": "Unexpected HF response format",
                "raw": response.text
            })
            continue

        parsed = _extract_json(content)
        if parsed is None:
            model_errors.append({
                "model": active_model,
                "error": "Could not parse JSON from model",
                "raw_output": content
            })
            continue

        # Accept either {"questions":[...]} or a bare JSON array and normalize.
        if isinstance(parsed, dict):
            questions = parsed.get("questions")
        elif isinstance(parsed, list):
            questions = parsed
            parsed = {"questions": questions}
        else:
            model_errors.append({
                "model": active_model,
                "error": "Model returned unsupported JSON shape",
                "parsed": parsed
            })
            continue

        if not isinstance(questions, list):
            model_errors.append({
                "model": active_model,
                "error": "Questions field is not a list",
                "parsed": parsed
            })
            continue

        # If model returns extra questions, trim. If fewer, keep failing clearly.
        if len(questions) > num_questions:
            questions = questions[:num_questions]
            parsed["questions"] = questions

        if len(questions) != num_questions:
            model_errors.append({
                "model": active_model,
                "error": "Model returned invalid number of questions",
                "count": len(questions)
            })
            continue

        invalid_structure = False
        normalized_questions = []
        for idx, q in enumerate(questions, start=1):
            if not isinstance(q, dict):
                invalid_structure = True
                break

            question_text = str(q.get("question", "")).strip()
            options = q.get("options")
            answer = q.get("answer")

            if not question_text or not isinstance(options, list) or len(options) != 4:
                invalid_structure = True
                break

            if isinstance(answer, str) and answer.isdigit():
                answer = int(answer)

            if not isinstance(answer, int) or answer < 0 or answer > 3:
                invalid_structure = True
                break

            normalized_questions.append({
                "id": idx,
                "question": question_text,
                "options": [str(opt).strip() for opt in options],
                "answer": answer
            })

        if invalid_structure:
            model_errors.append({
                "model": active_model,
                "error": "Invalid question structure from model"
            })
            continue

        parsed["questions"] = normalized_questions
        return parsed

    return {
        "error": "All configured MCQ models failed",
        "details": model_errors
    }
