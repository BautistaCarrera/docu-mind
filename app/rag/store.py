import os
import sqlite3
import uuid

import chromadb
from app.core.config import CHROMA_DIR

_client = None


def get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _client


def get_collection(session_id: str):
    client = get_client()
    # Cosine distance (0 = idéntico, 2 = opuesto) para poder fijar un umbral
    # de relevancia predecible al filtrar resultados de baja calidad.
    return client.get_or_create_collection(
        name=f"session_{session_id}",
        metadata={"hnsw:space": "cosine"},
    )


def delete_collection(session_id: str):
    """Borra la colección de la sesión y recupera el espacio en disco.

    OJO (encontrado en QA — ver TESTING.md): `client.delete_collection()`
    deja la colección inaccesible a nivel API, pero NO reduce el tamaño
    real del archivo `chroma.sqlite3` en disco — es el comportamiento
    estándar de SQLite, que marca las páginas como libres pero no las
    devuelve al sistema de archivos sin un VACUUM explícito. Sin este fix,
    una demo pública de larga duración crece en disco para siempre aunque
    el TTL de sesiones funcione bien a nivel aplicación.

    Limitación conocida que queda: además del `.sqlite3`, cada colección
    deja una carpeta con el índice HNSW (unos pocos cientos de KB) que no
    se puede identificar ni borrar de forma confiable desde afuera de
    Chroma sin depender de sus internals no documentados. Es un leak chico
    comparado con el del sqlite (que este fix sí resuelve), documentado en
    TESTING.md como pendiente.
    """
    client = get_client()
    try:
        client.delete_collection(name=f"session_{session_id}")
    except Exception:
        return  # ya no existía, nada que limpiar

    try:
        db_path = os.path.join(CHROMA_DIR, "chroma.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.execute("VACUUM")
        conn.close()
    except Exception:
        pass  # si el VACUUM falla, la colección ya quedó borrada igual


def add_chunks(session_id: str, filename: str, chunks: list[dict], embeddings: list[list[float]]):
    """`filename` queda en la metadata de cada chunk — necesario para citar
    de qué documento salió cada dato cuando un chat tiene varios documentos
    activos a la vez (ver app/core/sessions.py). Los ids usan uuid4 en vez
    de `f'{session_id}_{i}'`: con ids secuenciales por índice, subir un
    SEGUNDO documento a la misma sesión pisaba los chunks del primero en
    Chroma (mismos ids 0,1,2...) sin ningún error ni aviso."""
    collection = get_collection(session_id)
    ids = [str(uuid.uuid4()) for _ in chunks]
    documents = [c["text"] for c in chunks]
    metadatas = [{"page": c["page"], "filename": filename} for c in chunks]
    collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)


def query_collection(session_id: str, query_embedding: list[float], top_k: int = 4):
    collection = get_collection(session_id)
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )


def get_all_chunks(session_id: str, filename: str) -> list[dict]:
    """Todos los chunks de UN documento específico, en orden — no por
    similitud. Necesario para resúmenes: pedir 'resumime el documento' no
    se parece semánticamente a ningún fragmento puntual, así que el
    retrieval normal (top-k por similitud) devuelve pedazos random que no
    alcanzan para armar un resumen real (encontrado en QA manual: el LLM
    terminaba diciendo NO_SE no porque faltara información, sino porque
    los 4 fragmentos que le llegaban no eran representativos del
    documento completo)."""
    collection = get_collection(session_id)
    results = collection.get(where={"filename": filename}, include=["documents", "metadatas"])
    chunks = [
        {"text": d, "page": m.get("page")}
        for d, m in zip(results["documents"], results["metadatas"])
    ]
    chunks.sort(key=lambda c: c["page"] or 0)
    return chunks
