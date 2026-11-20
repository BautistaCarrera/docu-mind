from google import genai
from app.core.config import GEMINI_API_KEY, GEMINI_MODEL

SYSTEM_PROMPT = """Sos un asistente de soporte que responde preguntas SOLO usando el
contexto que te paso a continuación (extraído de un documento real del usuario).

Reglas estrictas:
- Si la respuesta está en el contexto, respondé de forma clara y breve.
- Si la pregunta asume algo que el contexto contradice o matiza (ej: preguntan
  "¿puedo hacer X al 100%?" y el contexto dice que solo se permite parcialmente),
  corregí la premisa usando la información real del contexto — no la ignores.
- Si la pregunta es una continuación de la conversación (ej: "¿y cuánto tarda?"
  después de preguntar por el envío), usá el historial de abajo para entender a
  qué se refiere, pero respondé SOLO con información que esté en el contexto.
- Nunca inventes información que no esté en el contexto.
- Si el contexto no tiene NADA relacionado con la pregunta, respondé ÚNICA Y
  EXACTAMENTE la palabra NO_SE — sin explicar por qué, sin texto antes ni
  después, nada más que esa palabra sola.
"""

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def generate_answer(question: str, context_chunks: list[dict], history: list[dict] | None = None) -> dict:
    if not GEMINI_API_KEY:
        return {
            "answer": "Falta configurar GEMINI_API_KEY en el .env del servidor.",
            "escalate": True,
        }

    if not context_chunks:
        return {
            "answer": "No tengo esa información en el documento. Te conecto con una persona del equipo.",
            "escalate": True,
        }

    context_text = "\n\n".join(
        f"[Página {c['page']}]: {c['text']}" for c in context_chunks
    )

    history_text = ""
    if history:
        turns = "\n".join(
            f"Usuario: {h['question']}\nAsistente: {h['answer']}" for h in history
        )
        history_text = f"\n\nHistorial reciente de la conversación:\n{turns}"

    prompt = (
        f"{SYSTEM_PROMPT}{history_text}\n\nContexto:\n{context_text}"
        f"\n\nPregunta actual: {question}\n\nRespuesta:"
    )

    client = _get_client()
    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        answer = (response.text or "").strip()
    except Exception as exc:  # noqa: BLE001 - cualquier falla de la API no debe tumbar el chat
        return {
            "answer": "Tuve un problema para responder en este momento. Te conecto con una persona del equipo. 🙋",
            "escalate": True,
            "error": str(exc),
        }

    # No usamos startswith: el LLM a veces agrega su razonamiento antes de
    # la palabra clave a pesar de la instrucción explícita (encontrado en
    # QA — ver TESTING.md). Buscar NO_SE en cualquier parte del texto es
    # más robusto, y de paso evita filtrar ese razonamiento interno al
    # usuario final.
    escalate = "NO_SE" in answer.upper()
    if escalate:
        answer = "No tengo esa información en el documento. Te conecto con una persona del equipo para que te ayude mejor. 🙋"

    return {"answer": answer, "escalate": escalate}
