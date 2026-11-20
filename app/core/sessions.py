"""Metadata de sesiones en memoria + expiración (TTL) para que una demo
pública no acumule datos para siempre en disco."""
import time

from app.core.config import SESSION_TTL_HOURS, MAX_ACTIVE_SESSIONS
from app.rag.store import delete_collection

_sessions: dict[str, dict] = {}


MAX_HISTORY_TURNS = 3  # cuantos intercambios previos se recuerdan por sesión


def create_session(session_id: str, filename: str, chunks: int, unit_label: str = "página"):
    _cleanup_expired()
    _sessions[session_id] = {
        "filename": filename,
        "chunks": chunks,
        "unit_label": unit_label,
        "created_at": time.time(),
        "history": [],
    }


def session_exists(session_id: str) -> bool:
    _cleanup_expired()
    return session_id in _sessions


def get_unit_label(session_id: str) -> str:
    """'página' para PDF, 'sección' para .txt/.docx (no tienen paginación
    real — citar 'página 3' de un .txt sería una cita falsa)."""
    session = _sessions.get(session_id)
    return session["unit_label"] if session else "página"


def get_history(session_id: str) -> list[dict]:
    """Últimos intercambios (pregunta/respuesta) de la sesión, para resolver
    preguntas de seguimiento tipo '¿y cuánto tarda?' sin repetir el tema."""
    session = _sessions.get(session_id)
    return session["history"] if session else []


def add_to_history(session_id: str, question: str, answer: str):
    session = _sessions.get(session_id)
    if session is None:
        return
    session["history"].append({"question": question, "answer": answer})
    session["history"] = session["history"][-MAX_HISTORY_TURNS:]


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
