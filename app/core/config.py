import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
# TOP_K=4 alcanzaba con pocos documentos, pero con muchos cargados a la vez
# (probado con 10: 8 PDF + 2 TXT) una pregunta que toca 3 temas distintos se
# quedaba sin lugar para el tercero si dos documentos "gemelos" (ej. dos
# empresas con política de envíos, o dos productos con garantía) ocupaban
# los 4 lugares por compartir vocabulario con la pregunta — el chunk
# correcto existía (distancia 0.698, dentro del umbral 0.75) pero ni
# llegaba a pedirse. Subido a 8: sigue siendo barato (Gemini soporta
# contexto enorme) y confirmado que no mezcla documentos aunque haya más
# candidatos "distractores" en el contexto (ver TESTING.md).
TOP_K = int(os.getenv("TOP_K", "8"))
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
