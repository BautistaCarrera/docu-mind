from google import genai
from google.genai import types
from app.core.config import GEMINI_API_KEY, GEMINI_MODEL

LLM_TIMEOUT_MS = 20_000  # 20s — ver nota en _get_client sobre por qué hace falta
SUMMARY_TIMEOUT_MS = 60_000  # un resumen manda MUCHO más contexto, tarda más en generarse

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
- El contexto puede venir de MÁS DE UN documento distinto (cada fragmento
  indica de cuál). Si la pregunta se puede responder con uno solo, usá ese.
  Si hace falta combinar datos de varios, dejá explícito de qué documento
  sale cada dato (ej: "Según manual.pdf, X. Según politica.docx, Y.").
  Nunca mezcles datos de documentos distintos como si fueran una sola
  afirmación sin aclarar la fuente de cada uno — eso sería inventar una
  relación entre los documentos que el contexto no dice.
"""

SUMMARY_SYSTEM_PROMPT = """Sos un asistente que resume documentos reales de forma fiel.

Reglas estrictas:
- Resumí SOLO lo que está en el texto de abajo — nunca agregues datos,
  secciones o conclusiones que no estén explícitamente ahí.
- Sé conciso: cubrí los puntos principales en pocos párrafos, no copies el
  documento casi entero ni hagas una lista interminable de cada detalle.
- Si el texto parece incompleto o cortado, resumí igual lo que sí está —
  no inventes cómo sigue ni asumas contenido que no ves.
"""

_client = None
_summary_client = None


def _get_client():
    """OJO (encontrado por un usuario probando a mano, no en mi QA): la
    llamada a Gemini no tenía ningún timeout. Si la API de Google tarda o
    se degrada, el request quedaba esperando indefinidamente — y como el
    frontend tampoco tiene ningún indicador de carga, eso se ve EXACTAMENTE
    igual que 'el agente dejó de responder', aunque técnicamente seguía
    esperando. Con el timeout, como mucho tarda `LLM_TIMEOUT_MS` y cae al
    mensaje de escalamiento normal en vez de colgarse."""
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=LLM_TIMEOUT_MS),
        )
    return _client


def _get_summary_client():
    """Cliente aparte con timeout más largo — un resumen manda mucho más
    contexto que una pregunta puntual (hasta `MAX_SUMMARY_CHARS`), y
    `LLM_TIMEOUT_MS` (pensado para preguntas cortas) cortaría de más."""
    global _summary_client
    if _summary_client is None:
        _summary_client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=SUMMARY_TIMEOUT_MS),
        )
    return _summary_client


# El modelo (gemini-3.5-flash-lite) soporta ~1.048.576 tokens de entrada —
# verificado contra la API real, no asumido. 500.000 caracteres (~125K
# tokens) cubre cualquier documento razonable (manuales, reglamentos,
# CVs de cientos de páginas) dejando margen de sobra, sin dejar de tener
# un tope ante un archivo patológicamente grande que dispararía costo y
# latencia sin necesidad real.
MAX_SUMMARY_CHARS = 500_000


def generate_summary(filename: str, unit_label: str, chunks: list[dict]) -> dict:
    """Resume un documento COMPLETO (no por similitud — ver store.get_all_chunks
    y el porqué en su docstring). Documentos muy largos se truncan con
    aviso explícito en vez de fallar o inventar el resto."""
    if not GEMINI_API_KEY:
        return {"answer": "Falta configurar GEMINI_API_KEY en el .env del servidor.", "escalate": True}

    if not chunks:
        return {
            "answer": f'No tengo contenido indexado de "{filename}" para resumir.',
            "escalate": True,
        }

    full_text = "\n\n".join(f"[{unit_label} {c['page']}]: {c['text']}" for c in chunks)
    truncated = len(full_text) > MAX_SUMMARY_CHARS
    if truncated:
        full_text = full_text[:MAX_SUMMARY_CHARS]

    prompt = (
        f"{SUMMARY_SYSTEM_PROMPT}\n\nDocumento ({filename}):\n{full_text}\n\nResumen:"
    )

    client = _get_summary_client()
    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        answer = (response.text or "").strip()
    except Exception as exc:  # noqa: BLE001
        return {
            "answer": "Tuve un problema para generar el resumen en este momento. Te conecto con una persona del equipo. 🙋",
            "escalate": True,
            "error": str(exc),
        }

    if truncated:
        answer += f"\n\n⚠️ El documento es muy largo, resumí solo la primera parte (~{MAX_SUMMARY_CHARS:,} caracteres)."

    return {"answer": answer, "escalate": False}


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
        f"[Documento: {c['filename']} — {c['unit_label']} {c['page']}]: {c['text']}"
        for c in context_chunks
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
