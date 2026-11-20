from sentence_transformers import SentenceTransformer

_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        # Modelo liviano, corre local en CPU, cero costo de API.
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_model()
    return model.encode(texts, convert_to_numpy=True).tolist()
