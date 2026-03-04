# SimuHire

AI-driven hiring workflow with:
- Candidate application intake
- HR screening dashboard
- MCQ interview round
- Virtual interview round with scoring

## Local Run

1. Create and activate virtual env.
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Copy env template and fill secrets:
```bash
cp .env.example .env
```
4. Start app:
```bash
python app.py
```

## GitHub Prep

1. Ensure `.env` is not committed (already ignored).
2. Commit and push:
```bash
git init
git add .
git commit -m "Prepare SimuHire for deployment"
git branch -M main
git remote add origin <your_repo_url>
git push -u origin main
```

## Deploy On Vercel

This repo includes `vercel.json` for Flask deployment.

1. Import project from GitHub in Vercel dashboard.
2. Set Environment Variables from `.env.example`.
3. Deploy.

## Important Production Note

Vercel filesystem is ephemeral. Resume uploads stored on local disk are temporary.
For production-grade persistence, store resumes in cloud storage (S3/Cloudinary/Firebase Storage) and save URLs in MongoDB.
