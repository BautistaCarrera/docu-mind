import io

from docx import Document
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = (".pdf", ".txt", ".docx")


def extract_content(filename: str, file_bytes: bytes) -> tuple[list[str], str]:
    """Dispatcher por extensión. Devuelve (unidades, etiqueta) donde:
    - `unidades` es una lista de strings para pasarle a chunk_pages (cada
      una se cita después como una unidad separada: página real para PDF,
      sección aproximada para .txt/.docx que no tienen paginación real).
    - `etiqueta` es la palabra a mostrarle al usuario en la cita
      ("página" vs "sección") — no queremos decir "página 3" de un .txt,
      sería una cita falsa (el archivo no tiene páginas reales).

    Lanza ValueError con mensaje claro si el archivo está corrupto o no es
    del formato que dice ser, para no filtrar un 500 crudo al usuario.
    """
    name = filename.lower()
    if name.endswith(".pdf"):
        return _extract_pdf(file_bytes), "página"
    if name.endswith(".docx"):
        return _extract_docx(file_bytes), "sección"
    if name.endswith(".txt"):
        return _extract_txt(file_bytes), "sección"
    raise ValueError(f"Extensión no soportada. Aceptamos: {', '.join(SUPPORTED_EXTENSIONS)}")


def _extract_pdf(file_bytes: bytes) -> list[str]:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        return [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # pypdf tiene varios tipos de error de bajo nivel
        raise ValueError(f"El archivo no es un PDF válido o está corrupto: {exc}") from exc


def _extract_docx(file_bytes: bytes) -> list[str]:
    try:
        doc = Document(io.BytesIO(file_bytes))
        full_text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:  # python-docx lanza BadZipFile / PackageNotFoundError, etc.
        raise ValueError(f"El archivo no es un .docx válido o está corrupto: {exc}") from exc
    return _split_into_sections(full_text)


def _extract_txt(file_bytes: bytes) -> list[str]:
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        # Muchos .txt viejos vienen en latin-1 — mejor degradar que rechazar
        # un archivo de texto plano real solo por el encoding.
        text = file_bytes.decode("latin-1", errors="replace")
    return _split_into_sections(text)


def _split_into_sections(text: str, max_chars: int = 3000) -> list[str]:
    """Agrupa párrafos en bloques de ~max_chars para que .txt/.docx tengan
    algo parecido a 'páginas' que citar, sin pretender que son páginas
    reales (de ahí la etiqueta 'sección' en vez de 'página')."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [text.strip()] if text.strip() else []

    sections, current = [], ""
    for p in paragraphs:
        if current and len(current) + len(p) > max_chars:
            sections.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        sections.append(current)
    return sections
