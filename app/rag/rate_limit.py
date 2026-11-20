import time

_session_counts: dict[str, dict] = {}
_ip_message_counts: dict[str, dict] = {}
_ip_upload_counts: dict[str, dict] = {}

MAX_MESSAGES_PER_SESSION = 20
WINDOW_SECONDS = 3600


def _check(store: dict, key: str, limit: int) -> bool:
    now = time.time()
    record = store.get(key, {"count": 0, "start": now})
    if now - record["start"] > WINDOW_SECONDS:
        record = {"count": 0, "start": now}
    record["count"] += 1
    store[key] = record
    return record["count"] <= limit


def check_rate_limit(session_id: str) -> bool:
    """Límite de mensajes por sesión individual."""
    return _check(_session_counts, session_id, MAX_MESSAGES_PER_SESSION)


def check_rate_limit_ip(ip: str, max_messages_per_ip: int) -> bool:
    """Límite de mensajes por IP, sumando todas sus sesiones — evita que
    alguien esquive el límite por sesión creando sesiones nuevas sin parar."""
    return _check(_ip_message_counts, ip, max_messages_per_ip)


def check_upload_limit_ip(ip: str, max_uploads_per_ip: int) -> bool:
    """Límite de documentos subidos por IP por hora."""
    return _check(_ip_upload_counts, ip, max_uploads_per_ip)
