"""Bot de Telegram para DocuMind.

Reemplaza la interfaz web (HTML/JS + FastAPI) por completo. El motor RAG
(`app/rag/*`) no cambió nada — solo cambió la "puerta de entrada": en vez
de un formulario web con `session_id` en la URL, cada CHAT de Telegram es
una sesión. El usuario manda un documento como archivo adjunto, y después
le pregunta por texto normal, como a cualquier contacto.

Ventaja real sobre la versión web (no es solo estética): el rate limiting
pasa a usar el `user_id` que entrega la propia API de Telegram, autenticado
en cada update — ya no hay header de IP que falsificar (ver TESTING.md
bug #5, el bypass de `X-Forwarded-For`, que acá directamente no existe
como superficie de ataque).

Un chat puede tener VARIOS documentos activos a la vez (ver
app/core/sessions.py) — probado en QA manual: mandar un segundo documento
pisaba al primero en silencio en la primera versión de este bot. Ahora se
acumulan, y cada respuesta cita explícitamente de qué documento sale cada
dato (ver app/rag/llm.py), para no mezclar información de documentos
distintos como si fuera una sola fuente.
"""
import logging
import re
import unicodedata
from difflib import get_close_matches

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from app.core.config import (
    TELEGRAM_BOT_TOKEN,
    MAX_FILE_SIZE_MB,
    TOP_K,
    SIMILARITY_THRESHOLD,
    MAX_MESSAGES_PER_USER,
    MAX_UPLOADS_PER_USER,
)
from app.core import sessions
from app.rag.ingest import extract_content, SUPPORTED_EXTENSIONS
from app.rag.chunking import chunk_pages
from app.rag.embeddings import embed_texts
from app.rag.store import add_chunks, query_collection, get_all_chunks
from app.rag.llm import generate_answer, generate_summary
from app.rag.rate_limit import check_rate_limit, check_rate_limit_user, check_upload_limit_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

WELCOME = (
    "👋 Soy DocuMind. Mandame uno o varios documentos (PDF, TXT o DOCX) como archivo "
    "adjunto y después preguntame lo que quieras sobre su contenido.\n\n"
    "Si tengo varios documentos cargados, te digo de cuál saqué cada dato — nunca mezclo "
    "información de distintos documentos como si fuera una sola fuente.\n\n"
    "Si no encuentro la respuesta en ninguno, te lo digo en vez de inventar.\n\n"
    "Comandos: /documentos (ver qué tenés cargado) · /reset (empezar de cero)"
)

SUMMARY_KEYWORDS = ("resum", "resúm", "sintetiz", "síntesis", "de qué trata", "sobre qué trata")


def _normalize(text: str) -> str:
    """Saca acentos y pasa a minúsculas — en Telegram la gente escribe
    'que' en vez de 'qué' todo el tiempo (encontrado en QA manual: 'de qué
    trata' con tilde no matcheaba 'de que trata' sin tilde, un mensaje
    real y común)."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _is_summary_request(message: str) -> bool:
    lowered = _normalize(message)
    return any(_normalize(kw) in lowered for kw in SUMMARY_KEYWORDS)


def _match_documents(message: str, documents: list[dict]) -> list[dict]:
    """A qué documento(s) cargados se refiere el mensaje, comparando el
    nombre de archivo (sin extensión) contra el texto — no exacto a
    propósito, porque el usuario puede escribir mal el nombre (ej:
    'reglamento grandt' en vez de 'Reglamento Grande.pdf'). Encontrado en
    QA manual: pedir un resumen por similitud semántica no funciona (ver
    store.get_all_chunks), así que primero hay que resolver A QUÉ
    documento se refiere antes de poder resumirlo.

    Devuelve solo el/los documento(s) con el MEJOR puntaje, no cualquiera
    que supere un piso bajo — con archivos que comparten un prefijo común
    (ej. 'Contrato_2024_clienteA.pdf' y 'Contrato_2024_clienteB.pdf'), un
    umbral flojo hacía que ESE prefijo solo ya alcanzara para matchear
    todos los documentos por igual (encontrado en QA manual con archivos
    de prueba que compartían prefijo 'qa3_')."""
    lowered = _normalize(message)
    words_in_message = re.findall(r"\w+", lowered)
    scored = []
    for doc in documents:
        stem = _normalize(re.sub(r"\.[a-z0-9]+$", "", doc["filename"]))
        stem_words = [w for w in re.split(r"[\s_\-]+", stem) if len(w) > 2]
        if not stem_words:
            continue
        hits = sum(
            1 for w in stem_words
            if w in lowered or get_close_matches(w, words_in_message, n=1, cutoff=0.75)
        )
        score = hits / len(stem_words)
        if score > 0:
            scored.append((doc, score))

    if not scored:
        return []
    best_score = max(score for _, score in scored)
    if best_score < 0.5:
        return []
    return [doc for doc, score in scored if score >= best_score - 1e-9]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def list_documents_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    docs = sessions.list_documents(chat_id)
    if not docs:
        await update.message.reply_text("No tenés ningún documento cargado todavía.")
        return
    lines = [f"• {d['filename']} ({d['chunks']} fragmentos)" for d in docs]
    await update.message.reply_text("Documentos activos en este chat:\n" + "\n".join(lines))


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    sessions.clear_documents(chat_id)
    await update.message.reply_text("Listo, borré todos tus documentos. Mandame uno nuevo cuando quieras.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa un documento subido. Reusa exactamente la misma lógica de
    extracción/chunking/embeddings que tenía /api/upload en la versión web.

    Se AGREGA a los documentos ya activos en este chat, no los reemplaza
    (ver docstring del módulo — encontrado roto en QA manual)."""
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    doc = update.message.document

    if not check_upload_limit_user(user_id, MAX_UPLOADS_PER_USER):
        await update.message.reply_text(
            "Límite de documentos subidos alcanzado por esta hora. Probá de nuevo más tarde."
        )
        return

    filename = doc.file_name or ""
    if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
        await update.message.reply_text(
            f"Extensión no soportada. Aceptamos: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
        return

    if doc.file_size and doc.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        await update.message.reply_text(f"El archivo supera el límite de {MAX_FILE_SIZE_MB}MB.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    tg_file = await context.bot.get_file(doc.file_id)
    content = bytes(await tg_file.download_as_bytearray())

    try:
        pages, unit_label = extract_content(filename, content)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    if not any(p.strip() for p in pages):
        hint = " (¿es un escaneo sin OCR?)" if filename.lower().endswith(".pdf") else ""
        await update.message.reply_text(f"No se pudo extraer texto del archivo.{hint}")
        return

    chunks = chunk_pages(pages)
    if not chunks:
        await update.message.reply_text("El documento no tiene contenido para indexar.")
        return

    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)

    # El chat_id de Telegram ES la sesión — a diferencia de la web, acá no
    # hace falta inventar un UUID y devolverlo al cliente: Telegram ya nos
    # da un identificador estable y persistente por conversación.
    add_chunks(chat_id, filename, chunks, embeddings)
    sessions.add_document(chat_id, filename, len(chunks), unit_label)

    total_docs = len(sessions.list_documents(chat_id))
    extra = f" Ahora tenés {total_docs} documentos activos — te respondo citando de cuál sale cada dato." if total_docs > 1 else ""
    await update.message.reply_text(
        f'Listo: "{filename}" indexado ({len(chunks)} fragmentos).{extra} Preguntame lo que quieras.'
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trata cualquier mensaje de texto como una pregunta a los documentos
    activos de este chat. Reusa la misma lógica de retrieval + generación
    que tenía /api/chat en la versión web, extendida para citar el
    documento de origen de cada fragmento (no solo la página/sección)."""
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    message = (update.message.text or "").strip()

    if not message:
        return
    if not sessions.session_exists(chat_id):
        await update.message.reply_text("Todavía no subiste ningún documento. Mandame uno primero.")
        return
    if not check_rate_limit(chat_id):
        await update.message.reply_text("Límite de mensajes alcanzado para esta sesión.")
        return
    if not check_rate_limit_user(user_id, MAX_MESSAGES_PER_USER):
        await update.message.reply_text("Límite de mensajes alcanzado por esta hora. Probá más tarde.")
        return

    # Indicador de "escribiendo..." — versión Telegram del "Pensando..."
    # que agregamos en la web después de que un usuario real reportara que
    # la app parecía colgada sin ningún feedback visual (ver TESTING.md
    # bug #11). Acá Telegram lo resuelve nativo con sendChatAction.
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # Pedido de resumen: NO pasa por el retrieval normal (ver docstring de
    # store.get_all_chunks) — necesita el documento completo, no los top-k
    # fragmentos más "parecidos" a la palabra "resumen" (que no se parece
    # semánticamente a ningún contenido real, encontrado en QA manual).
    if _is_summary_request(message):
        all_docs = sessions.list_documents(chat_id)
        matched = _match_documents(message, all_docs)
        if not matched and len(all_docs) == 1:
            matched = all_docs  # un solo documento cargado: no hay ambigüedad posible
        if not matched:
            names = ", ".join(d["filename"] for d in all_docs) if all_docs else "ninguno todavía"
            await update.message.reply_text(
                f"No identifiqué a qué documento te referís. Los que tenés cargados son: {names}. "
                "Probá escribiendo el nombre del archivo."
            )
            return
        for doc in matched:
            chunks = get_all_chunks(chat_id, doc["filename"])
            result = generate_summary(doc["filename"], doc["unit_label"], chunks)
            sessions.add_to_history(chat_id, f"Resumen de {doc['filename']}", result["answer"])
            await update.message.reply_text(f"📄 {doc['filename']}:\n\n{result['answer']}")
        return

    query_embedding = embed_texts([message])[0]
    results = query_collection(chat_id, query_embedding, top_k=TOP_K)

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    history = sessions.get_history(chat_id)

    if not any(dist <= SIMILARITY_THRESHOLD for dist in distances) and history:
        contextual_query = f"{history[-1]['question']} {message}"
        contextual_embedding = embed_texts([contextual_query])[0]
        results = query_collection(chat_id, contextual_embedding, top_k=TOP_K)
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

    # Mensajes largos con relleno/rodeos antes de la pregunta real diluyen
    # la pregunta en el embedding de toda la frase (medido en QA: con 50+
    # palabras de relleno antes de la pregunta, la distancia pasa de 0.40 a
    # 0.94 — deja de matchear). No es solo un caso de laboratorio: alguien
    # real puede escribir un párrafo de contexto antes de ir al grano. Si
    # los intentos de arriba fallaron y el mensaje es largo, reintentamos
    # con solo la "cola" (últimos ~150 caracteres), donde suele estar la
    # pregunta real.
    if not any(dist <= SIMILARITY_THRESHOLD for dist in distances) and len(message) > 250:
        tail_embedding = embed_texts([message[-150:]])[0]
        results = query_collection(chat_id, tail_embedding, top_k=TOP_K)
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

    relevant_chunks = [
        {
            "text": d,
            "page": m.get("page"),
            "filename": m.get("filename", "documento"),
            "unit_label": sessions.get_unit_label(chat_id, m.get("filename", "")),
        }
        for d, m, dist in zip(documents, metadatas, distances)
        if dist <= SIMILARITY_THRESHOLD
    ]

    if not relevant_chunks:
        await update.message.reply_text(
            "No tengo esa información en ninguno de tus documentos. Te conecto con una persona "
            "del equipo para que te ayude mejor. 🙋"
        )
        return

    result = generate_answer(message, relevant_chunks, history=history)
    sessions.add_to_history(chat_id, message, result["answer"])

    text = result["answer"]
    if not result["escalate"]:
        # Agrupado por documento: "manual.pdf (página 1, 2), notas.txt
        # (sección 1)" — nunca una lista plana de números que no diga de
        # qué archivo son, sobre todo con varios documentos activos.
        by_doc: dict[str, dict] = {}
        for c in relevant_chunks:
            by_doc.setdefault(c["filename"], {"label": c["unit_label"], "pages": set()})
            by_doc[c["filename"]]["pages"].add(c["page"])
        parts = [
            f"{fname} ({info['label']} {', '.join(str(p) for p in sorted(info['pages']))})"
            for fname, info in by_doc.items()
        ]
        text += f" (Fuente: {'; '.join(parts)})"

    await update.message.reply_text(text)


async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fotos, audios, stickers, etc. — en vez de ignorarlos en silencio,
    explicar qué sí se puede mandar (encontrado útil en QA de la versión
    web: un mensaje claro ahorra confusión del usuario)."""
    await update.message.reply_text(
        f"Solo puedo procesar documentos como archivo adjunto ({', '.join(SUPPORTED_EXTENSIONS)}) "
        "o preguntas de texto."
    )


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN en el .env — creá el bot con @BotFather primero.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("documentos", list_documents_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.Document.ALL & ~filters.COMMAND, handle_unsupported))

    logger.info("Bot arrancando (polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
