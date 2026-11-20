import time

_session_counts: dict[str, dict] = {}
_user_message_counts: dict[int, dict] = {}
_user_upload_counts: dict[int, dict] = {}

MAX_MESSAGES_PER_SESSION = 20
WINDOW_SECONDS = 3600


def _check(store: dict, key, limit: int) -> bool:
    now = time.time()
    record = store.get(key, {"count": 0, "start": now})
    if now - record["start"] > WINDOW_SECONDS:
        record = {"count": 0, "start": now}
    record["count"] += 1
    store[key] = record
    return record["count"] <= limit


def check_rate_limit(session_id: str) -> bool:
    """Límite de mensajes por sesión individual (= por chat de Telegram)."""
    return _check(_session_counts, session_id, MAX_MESSAGES_PER_SESSION)


def check_rate_limit_user(user_id: int, max_messages_per_user: int) -> bool:
    """Límite de mensajes por usuario de Telegram, sumando todos sus chats.

    A diferencia de la versión web (rate limit por IP, esquivable
    falsificando `X-Forwarded-For` — ver TESTING.md bug #5), `user_id` lo
    asigna la propia API de Telegram y viaja autenticado en cada update:
    no hay forma de que el cliente lo falsifique desde la app."""
    return _check(_user_message_counts, user_id, max_messages_per_user)


def check_upload_limit_user(user_id: int, max_uploads_per_user: int) -> bool:
    """Límite de documentos subidos por usuario de Telegram por hora."""
    return _check(_user_upload_counts, user_id, max_uploads_per_user)
