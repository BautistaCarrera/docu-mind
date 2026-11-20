import os
import sqlite3

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


def add_chunks(session_id: str, chunks: list[dict], embeddings: list[list[float]]):
    collection = get_collection(session_id)
    ids = [f"{session_id}_{i}" for i in range(len(chunks))]
    documents = [c["text"] for c in chunks]
    metadatas = [{"page": c["page"]} for c in chunks]
    collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)


def query_collection(session_id: str, query_embedding: list[float], top_k: int = 4):
    collection = get_collection(session_id)
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
