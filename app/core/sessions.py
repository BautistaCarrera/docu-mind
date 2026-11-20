"""Metadata de sesiones en memoria + expiración (TTL) para que el bot no
acumule datos para siempre en disco.

Cada sesión (= cada chat de Telegram) puede tener VARIOS documentos
activos a la vez — no uno solo. Encontrado real: al mandar un segundo
documento al mismo chat, el primero se pisaba en silencio sin avisar
(`create_session` sobreescribía la sesión entera). Ahora los documentos
se ACUMULAN por chat, y cada chunk indexado en Chroma lleva el nombre de
archivo de origen (ver `app/rag/store.py`), así que al responder siempre
se puede citar de qué documento salió cada dato — sin mezclar información
de distintos documentos como si fuera una sola fuente."""
import time

from app.core.config import SESSION_TTL_HOURS, MAX_ACTIVE_SESSIONS
from app.rag.store import delete_collection

_sessions: dict[str, dict] = {}


MAX_HISTORY_TURNS = 3  # cuantos intercambios previos se recuerdan por sesión


def add_document(session_id: str, filename: str, chunks: int, unit_label: str = "página"):
    """Agrega un documento a la sesión — si ya había otros, se suman, no
    se pisan. Dos documentos con el mismo nombre se tratan como el mismo
    (se actualiza en vez de duplicar), para poder resubir sin acumular
    basura si alguien manda el mismo archivo dos veces."""
    _cleanup_expired()
    if session_id not in _sessions:
        _sessions[session_id] = {"documents": {}, "created_at": time.time(), "history": []}
    _sessions[session_id]["documents"][filename] = {"chunks": chunks, "unit_label": unit_label}


def session_exists(session_id: str) -> bool:
    _cleanup_expired()
    return session_id in _sessions and bool(_sessions[session_id]["documents"])


def list_documents(session_id: str) -> list[dict]:
    session = _sessions.get(session_id)
    if not session:
        return []
    return [
        {"filename": fname, "chunks": data["chunks"], "unit_label": data["unit_label"]}
        for fname, data in session["documents"].items()
    ]


def get_unit_label(session_id: str, filename: str) -> str:
    """'página' para PDF, 'sección' para .txt/.docx. Es por documento, no
    por sesión — un mismo chat puede tener un PDF y un TXT a la vez, cada
    uno con su propia etiqueta de cita."""
    session = _sessions.get(session_id)
    if not session:
        return "página"
    doc = session["documents"].get(filename)
    return doc["unit_label"] if doc else "página"


def clear_documents(session_id: str):
    """Borra todos los documentos de la sesión (comando /reset) — libera
    la colección entera de Chroma y arranca de cero."""
    if session_id in _sessions:
        _sessions.pop(session_id, None)
    delete_collection(session_id)


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
