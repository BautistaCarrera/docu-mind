import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
TOP_K = int(os.getenv("TOP_K", "4"))
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.6"))
MAX_MESSAGES_PER_IP = int(os.getenv("MAX_MESSAGES_PER_IP", "40"))
MAX_UPLOADS_PER_IP = int(os.getenv("MAX_UPLOADS_PER_IP", "8"))
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "2"))
MAX_ACTIVE_SESSIONS = int(os.getenv("MAX_ACTIVE_SESSIONS", "200"))
