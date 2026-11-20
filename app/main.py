import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core.config import (
    MAX_FILE_SIZE_MB,
    TOP_K,
    SIMILARITY_THRESHOLD,
    MAX_MESSAGES_PER_IP,
    MAX_UPLOADS_PER_IP,
    TRUST_PROXY_HEADERS,
)
from app.core import sessions
from app.rag.ingest import extract_pages
from app.rag.chunking import chunk_pages
from app.rag.embeddings import embed_texts
from app.rag.store import add_chunks, query_collection
from app.rag.llm import generate_answer
from app.rag.rate_limit import check_rate_limit, check_rate_limit_ip, check_upload_limit_ip

app = FastAPI(title="DocuMind API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str
    message: str


def get_client_ip(request: Request) -> str:
    """Toma la IP real del cliente para el rate limiting.

    OJO: X-Forwarded-For lo puede mandar el propio cliente y rotarlo en
    cada request — confiar en él ciegamente permite esquivar el límite
    por IP por completo (encontrado en QA). Solo se usa si TRUST_PROXY_HEADERS
    está activado explícitamente, para cuando la app corre detrás de un
    proxy de confianza (Render/Hugging Face Spaces) que lo sobreescribe
    con la IP real antes de que llegue a nosotros. Por defecto, se usa la
    IP de la conexión TCP (`request.client.host`), que el cliente no puede
    falsificar a nivel aplicación.
    """
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload")
def upload_document(request: Request, file: UploadFile = File(...)):
    """OJO: a propósito NO es `async def`. Acá adentro se hace trabajo de
    CPU pesado (parseo de PDF + generación de embeddings), que puede tardar
    varios segundos con documentos grandes. Si esto fuera `async def`,
    correría directo en el event loop de asyncio y bloquearía TODO el
    servidor para TODOS los usuarios mientras dura el procesamiento —
    incluso /api/health quedaría colgado (confirmado en QA: una subida de
    150 páginas bloqueó 6 health-checks concurrentes ~29s cada uno). Al
    dejarlo como `def` normal, FastAPI lo corre en un thread pool aparte,
    y el resto de la app sigue respondiendo mientras tanto.
    """
    client_ip = get_client_ip(request)
    if not check_upload_limit_ip(client_ip, MAX_UPLOADS_PER_IP):
        raise HTTPException(
            429, "Límite de documentos subidos alcanzado para esta demo pública. Probá de nuevo más tarde."
        )

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF.")

    content = file.file.read()
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo supera el límite de {MAX_FILE_SIZE_MB}MB.")

    try:
        pages = extract_pages(content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    if not any(p.strip() for p in pages):
        raise HTTPException(400, "No se pudo extraer texto del PDF (¿es un escaneo sin OCR?).")

    chunks = chunk_pages(pages)
    if not chunks:
        raise HTTPException(400, "El documento no tiene contenido para indexar.")

    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)

    session_id = str(uuid.uuid4())
    add_chunks(session_id, chunks, embeddings)
    sessions.create_session(session_id, file.filename, len(chunks))

    return {
        "session_id": session_id,
        "filename": file.filename,
        "chunks_indexed": len(chunks),
    }


@app.post("/api/chat")
def chat(request: Request, req: ChatRequest):
    client_ip = get_client_ip(request)

    if not req.message.strip():
        raise HTTPException(400, "El mensaje no puede estar vacío.")
    if not sessions.session_exists(req.session_id):
        raise HTTPException(404, "Sesión no encontrada o expirada. Subí un documento de nuevo.")
    if not check_rate_limit(req.session_id):
        raise HTTPException(429, "Límite de mensajes alcanzado para esta sesión de demo.")
    if not check_rate_limit_ip(client_ip, MAX_MESSAGES_PER_IP):
        raise HTTPException(429, "Límite de mensajes alcanzado para esta demo pública. Probá de nuevo más tarde.")

    query_embedding = embed_texts([req.message])[0]
    results = query_collection(req.session_id, query_embedding, top_k=TOP_K)

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    history = sessions.get_history(req.session_id)

    # Si la búsqueda inicial no encuentra nada relevante, reintentamos
    # combinando la pregunta actual con la anterior — cubre preguntas de
    # seguimiento tipo "¿y cuánto tarda?" que por sí solas no tienen
    # suficiente contexto semántico para que el retrieval las matchee
    # (encontrado en QA: ver TESTING.md).
    if not any(dist <= SIMILARITY_THRESHOLD for dist in distances) and history:
        contextual_query = f"{history[-1]['question']} {req.message}"
        contextual_embedding = embed_texts([contextual_query])[0]
        results = query_collection(req.session_id, contextual_embedding, top_k=TOP_K)
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

    # Solo se consideran "fuente" los fragmentos realmente parecidos a la
    # pregunta — así no se cita una página que el modelo nunca usó.
    relevant_chunks = [
        {"text": d, "page": m.get("page")}
        for d, m, dist in zip(documents, metadatas, distances)
        if dist <= SIMILARITY_THRESHOLD
    ]

    if not relevant_chunks:
        return {
            "answer": "No tengo esa información en el documento. Te conecto con una persona del equipo para que te ayude mejor. 🙋",
            "sources": [],
            "escalate": True,
        }

    result = generate_answer(req.message, relevant_chunks, history=history)
    sources = sorted({c["page"] for c in relevant_chunks}) if not result["escalate"] else []

    sessions.add_to_history(req.session_id, req.message, result["answer"])

    return {"answer": result["answer"], "sources": sources, "escalate": result["escalate"]}


# Frontend estático servido al final para no pisar las rutas /api/*.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
