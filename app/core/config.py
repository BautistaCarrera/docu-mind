import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
TOP_K = int(os.getenv("TOP_K", "4"))
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.75"))
MAX_MESSAGES_PER_USER = int(os.getenv("MAX_MESSAGES_PER_USER", "40"))
MAX_UPLOADS_PER_USER = int(os.getenv("MAX_UPLOADS_PER_USER", "8"))
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "2"))
MAX_ACTIVE_SESSIONS = int(os.getenv("MAX_ACTIVE_SESSIONS", "200"))

# Nota histórica (ver TESTING.md bug #5): la versión web tenía rate
# limiting por IP, que se esquivaba falsificando el header
# `X-Forwarded-For`. Al mover todo a Telegram, el rate limit pasa a usar
# el `user_id` que manda la propia API de Telegram — no es un header que
# el cliente pueda falsificar a nivel aplicación, así que esa clase entera
# de bug queda eliminada de raíz, no parcheada.
