def chunk_pages(pages: list[str], chunk_size: int = 800, overlap: int = 150) -> list[dict]:
    """Parte el texto de cada página en fragmentos solapados, conservando
    el número de página para poder citar la fuente después."""
    chunks = []
    for page_num, text in enumerate(pages, start=1):
        text = (text or "").strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            end = start + chunk_size
            piece = text[start:end].strip()
            if piece:
                chunks.append({"text": piece, "page": page_num})
            next_start = end - overlap
            start = next_start if next_start > start else end
    return chunks
