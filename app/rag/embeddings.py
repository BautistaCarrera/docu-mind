from sentence_transformers import SentenceTransformer

_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        # Modelo multilingüe (ES/EN/PT/etc.) — liviano, corre local en CPU,
        # cero costo de API. Necesario porque muchos manuales/catálogos
        # reales vienen en inglés aunque el usuario pregunte en español.
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_model()
    return model.encode(texts, convert_to_numpy=True).tolist()
