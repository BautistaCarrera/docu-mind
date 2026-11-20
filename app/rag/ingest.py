import io
from pypdf import PdfReader


def extract_pages(file_bytes: bytes) -> list[str]:
    """Devuelve una lista con el texto de cada página del PDF.

    Lanza ValueError con un mensaje claro si el archivo no es un PDF válido
    o está corrupto — pypdf tira excepciones de bajo nivel (PdfStreamError,
    etc.) que no queremos que lleguen crudas al usuario como un 500.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        return [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # pypdf tiene varios tipos de error de bajo nivel
        raise ValueError(f"El archivo no es un PDF válido o está corrupto: {exc}") from exc
