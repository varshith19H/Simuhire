# SimuHire

SimuHire is an AI-assisted hiring platform built with Flask. It supports end-to-end candidate screening with:

- Candidate application intake (resume upload)
- HR shortlisting and credential sharing
- MCQ interview round with scoring
- Optional AI avatar virtual interview round
- Session-based candidate/HR portal workflows

---

## 1. What SimuHire Does

SimuHire automates early hiring stages by combining rule-based process control with AI-generated interview content.

### Candidate flow
1. Candidate applies with profile + PDF resume.
2. Resume is stored in Cloudinary; application is saved in MongoDB.
3. HR reviews and accepts/rejects.
4. Accepted candidate receives username/password by email.
5. Candidate logs in and takes MCQ interview.
6. HR may promote candidate to virtual round.
7. Candidate completes virtual interview; system stores score + feedback.

### HR/Admin flow
1. Login using `ADMIN_USER` and `ADMIN_PASS`.
2. View pending/selected/rejected pools.
3. Accept/reject applications.
4. Promote/reject candidates after MCQ round.
5. Review consolidated candidate results.

---

## 2. Tech Stack

- Backend: Flask
- Database: MongoDB (Atlas or local)
- Resume storage: Cloudinary
- AI generation/evaluation:
  - Ollama (optional/local)
  - Hugging Face Router API
  - Deterministic local fallback
- Optional avatar video generation: D-ID API
- Email delivery: SMTP

---

## 3. Project Structure (important files)

```text
app.py                 # Flask app, routes, interview logic, scoring, sessions
config.py              # Environment-driven configuration
ai/hf_generator.py     # MCQ generation helper
templates/main.html    # Main frontend shell and portal UI
static/                # CSS, JS, assets
.env.example           # Environment variable template
requirements.txt       # Python dependencies
```

---

## 4. Setup Instructions

## 4.1 Prerequisites

- Python 3.10+
- MongoDB connection (Atlas recommended)
- Cloudinary account (required for resume upload)
- SMTP account (required if you want auto email credentials)
- (Optional) Ollama running locally
- (Optional) D-ID credentials for avatar video endpoint

## 4.2 Installation

```powershell
# from project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4.3 Configure environment

1. Copy `.env.example` to `.env`
2. Fill required values (see next section)

```powershell
Copy-Item .env.example .env
```

## 4.4 Run application

```powershell
python app.py
```

Default local URL: `http://127.0.0.1:5000`

---

## 5. Environment Variables

### Core app

- `FLASK_SECRET`: Session secret key
- `FLASK_DEBUG`: `true` or `false`

### MongoDB

- `MONGO_URI`
- `MONGO_DB`
- `MONGO_SERVER_SELECTION_TIMEOUT_MS`
- `MONGO_CONNECT_TIMEOUT_MS`
- `MONGO_SOCKET_TIMEOUT_MS`

### Cloudinary (required for apply flow)

- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `CLOUDINARY_FOLDER`

### Admin login

- `ADMIN_USER`
- `ADMIN_PASS`

### SMTP (required for sending candidate credentials/updates)

- `SMTP_SERVER`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`

### AI settings

- `HF_TOKEN`
- `HF_API_URL`
- `HF_MODEL`
- `MCQ_SECONDARY_MODEL`
- `MCQ_TERTIARY_MODEL`
- `VIRTUAL_HF_MODEL`
- `VIRTUAL_HF_MAX_MODELS`
- `MCQ_USE_OLLAMA`
- `OLLAMA_URL`
- `OLLAMA_MODEL`
- `MCQ_OLLAMA_MODEL`
- `USE_LOCAL_VIRTUAL_MODEL`
- `MCQ_QUESTION_COUNT` (code enforces minimum 10)
- `VIRTUAL_QUESTION_COUNT` (code enforces minimum 5)

### D-ID (optional, only for `/api/virtual/avatar_question`)

- `DID_API_KEY`
- `DID_BASE_URL`
- `DID_AVATAR_SOURCE_URL`
- `DID_VOICE_PROVIDER`
- `DID_VOICE_ID`
- `DID_TALK_TIMEOUT_SECONDS`

---

## 6. API Endpoints Summary

## Public / Candidate Intake

- `GET /` - Load main frontend
- `POST /api/apply` - Submit candidate application + PDF resume
- `GET /resume/<path:resume_ref>` - Redirect to stored resume URL

## Admin

- `POST /api/admin/login` - Admin login
- `GET /api/admin/applications` - Fetch pending/rejected/selected lists
- `POST /api/admin/accept/<id>` - Accept application and create user credentials
- `POST /api/admin/reject/<id>` - Reject application
- `POST /api/admin/enable_virtual/<id>` - Alias of promote endpoint
- `POST /api/admin/virtual/promote/<id>` - Enable virtual round
- `POST /api/admin/virtual/reject/<id>` - Reject after MCQ

## Candidate Interview

- `POST /api/candidate/login` - Candidate login
- `POST /api/start_test` - Generate/start MCQ test
- `POST /api/submit_test` - Submit MCQ answers and score

## Virtual Interview

- `POST /api/virtual/questions` - Generate virtual questions
- `POST /api/virtual/avatar_question` - Generate avatar question video (D-ID)
- `POST /api/virtual/respond` - Generate interviewer response text
- `POST /api/virtual/submit` - Submit virtual round answers and score

## Session

- `GET /api/logout` - Clear session
- `GET /api/session/status` - Check active session role/status

---

## 7. Data Model (high level)

### `applications` collection
Stores initial applicants with resume URL and status (`pending`, `selected`, `rejected`).

### `users` collection
Stores accepted candidates, login credentials (hashed password), MCQ data, virtual-round state, and scores.

### `tests` collection
Stores generated MCQ question set per test session (`test_id`).

---

## 8. AI/Scoring Behavior

- MCQ generation uses provider fallback strategy:
  1. Ollama (if enabled)
  2. Hugging Face models
  3. Deterministic local question generator
- Virtual question generation and evaluation also include fallback logic.
- If model output is invalid or unavailable, SimuHire still continues with deterministic/local scoring paths.

---

## 9. Notes and Constraints

- Resume upload requires Cloudinary credentials; no local resume file persistence is used.
- Candidate credentials are emailed after HR acceptance; SMTP must be valid for successful delivery.
- Proctoring/flow control is enforced in frontend logic and validated through backend state.
- Flask session secret and admin credentials must be changed for production.

---

## 10. Quick Validation Checklist

1. Start app and open `/`.
2. Submit an application with a PDF resume.
3. Login as admin and accept candidate.
4. Verify credential email delivery.
5. Login as candidate and complete MCQ.
6. Promote candidate to virtual round from admin.
7. Complete virtual interview and verify stored score/feedback.

---

## 11. Deployment Notes

- This project includes `vercel.json` for deployment configuration.
- Ensure all `.env` variables are configured in your hosting platform.
- Do not commit `.env` or secret keys.

