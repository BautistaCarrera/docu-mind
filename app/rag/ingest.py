import io
from pypdf import PdfReader


def extract_pages(file_bytes: bytes) -> list[str]:
    """Devuelve una lista con el texto de cada página del PDF."""
    reader = PdfReader(io.BytesIO(file_bytes))
    return [page.extract_text() or "" for page in reader.pages]
