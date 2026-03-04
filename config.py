# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    HF_TOKEN = os.getenv("HF_TOKEN")
    HF_API_URL = os.getenv("HF_API_URL", "https://router.huggingface.co/v1/chat/completions")
    MODEL = os.getenv("HF_MODEL", "OpenAssistant/oasst-sft-4-pythia-12b-epoch-3.5")
    MCQ_SECONDARY_MODEL = os.getenv("MCQ_SECONDARY_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
    MCQ_TERTIARY_MODEL = os.getenv("MCQ_TERTIARY_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
    VIRTUAL_HF_MODEL = os.getenv("VIRTUAL_HF_MODEL", MODEL)
    USE_LOCAL_VIRTUAL_MODEL = os.getenv("USE_LOCAL_VIRTUAL_MODEL", "false").lower() == "true"
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    DID_API_KEY = os.getenv("DID_API_KEY")
    DID_BASE_URL = os.getenv("DID_BASE_URL", "https://api.d-id.com")
    DID_AVATAR_SOURCE_URL = os.getenv(
        "DID_AVATAR_SOURCE_URL",
        "https://create-images-results.d-id.com/DefaultPresenters/Noelle_f/image.png"
    )
    DID_VOICE_PROVIDER = os.getenv("DID_VOICE_PROVIDER", "microsoft")
    DID_VOICE_ID = os.getenv("DID_VOICE_ID", "en-US-JennyNeural")
    DID_TALK_TIMEOUT_SECONDS = int(os.getenv("DID_TALK_TIMEOUT_SECONDS", 60))

    # MongoDB
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/simuhire_db")
    MONGO_DB = os.getenv("MONGO_DB", "simuhire_db")

    # Cloudinary (resume storage)
    CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")
    CLOUDINARY_FOLDER = os.getenv("CLOUDINARY_FOLDER", "simuhire/resumes")

    # SMTP for sending candidate credentials (Gmail example)
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER = os.getenv("SMTP_USER")    # your email (set in .env)
    SMTP_PASS = os.getenv("SMTP_PASS")    # app password or smtp password

    # Admin credentials (set in .env). Default should be changed in production.
    ADMIN_USER = os.getenv("ADMIN_USER", "hr@simuhire.com")
    ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")  # change this in .env

    @classmethod
    def validate(cls):
        if not cls.HF_TOKEN:
            raise RuntimeError("HF_TOKEN not set in .env")
        if not cls.SMTP_USER or not cls.SMTP_PASS:
            print("Warning: SMTP_USER or SMTP_PASS not set. Emailing will fail.")
