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
    client = get_client()
    try:
        client.delete_collection(name=f"session_{session_id}")
    except Exception:
        pass  # si ya no existe, no pasa nada


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
