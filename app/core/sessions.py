"""Metadata de sesiones en memoria + expiración (TTL) para que una demo
pública no acumule datos para siempre en disco."""
import time

from app.core.config import SESSION_TTL_HOURS, MAX_ACTIVE_SESSIONS
from app.rag.store import delete_collection

_sessions: dict[str, dict] = {}


def create_session(session_id: str, filename: str, chunks: int):
    _cleanup_expired()
    _sessions[session_id] = {
        "filename": filename,
        "chunks": chunks,
        "created_at": time.time(),
    }


def session_exists(session_id: str) -> bool:
    _cleanup_expired()
    return session_id in _sessions


def _cleanup_expired():
    now = time.time()
    ttl_seconds = SESSION_TTL_HOURS * 3600

    expired = [
        sid for sid, data in _sessions.items()
        if now - data["created_at"] > ttl_seconds
    ]
    for sid in expired:
        _sessions.pop(sid, None)
        delete_collection(sid)

    # Tope duro: si por lo que sea hay demasiadas sesiones activas, se
    # purgan las más viejas aunque no hayan cumplido el TTL todavía.
    if len(_sessions) > MAX_ACTIVE_SESSIONS:
        oldest_first = sorted(_sessions.items(), key=lambda kv: kv[1]["created_at"])
        to_remove = len(_sessions) - MAX_ACTIVE_SESSIONS
        for sid, _ in oldest_first[:to_remove]:
            _sessions.pop(sid, None)
            delete_collection(sid)
