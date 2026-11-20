const API_BASE = "/api";
let sessionId = null;

const fileInput = document.getElementById("file-input");
const uploadBtn = document.getElementById("upload-btn");
const uploadStatus = document.getElementById("upload-status");
const chatSection = document.getElementById("chat-section");
const chatLog = document.getElementById("chat-log");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");

uploadBtn.addEventListener("click", async () => {
  const file = fileInput.files[0];
  if (!file) {
    uploadStatus.textContent = "Elegí un archivo primero (PDF, TXT o DOCX).";
    return;
  }
  uploadStatus.textContent = "Procesando documento...";
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Error al subir el archivo");
    sessionId = data.session_id;
    uploadStatus.textContent = `Listo: "${data.filename}" indexado (${data.chunks_indexed} fragmentos).`;
    chatSection.style.display = "block";
    addMessage("agent", `Ya leí tu documento "${data.filename}". Preguntame lo que quieras.`);
  } catch (err) {
    uploadStatus.textContent = `Error: ${err.message}`;
  }
});

sendBtn.addEventListener("click", sendMessage);
chatInput.addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });

let isSending = false;

async function sendMessage() {
  // Guard explícito: sin esto, mandar un segundo mensaje mientras el
  // primero todavía está esperando respuesta generaba confusión (encontrado
  // probando a mano) — ninguno de los dos mostraba nada hasta que ambos
  // volvían, y parecía que el agente se había quedado colgado.
  if (isSending) return;
  const message = chatInput.value.trim();
  if (!message || !sessionId) return;

  isSending = true;
  sendBtn.disabled = true;
  addMessage("user", message);
  chatInput.value = "";

  // Indicador de "pensando..." — antes no había NINGUNA señal visual
  // mientras se esperaba la respuesta. Un request que tarda unos segundos
  // (o más, si el LLM está lento) se veía exactamente igual que "el agente
  // no responde más", que es justo lo que reportó un usuario probándolo.
  const thinkingEl = addMessage("agent", "Pensando...", false, true);

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Error en el chat");
    let text = data.answer;
    if (data.sources && data.sources.length > 0) {
      const label = data.source_label || "página";
      text += ` (Fuente: ${label} ${data.sources.join(", ")})`;
    }
    thinkingEl.remove();
    addMessage("agent", text, data.escalate);
  } catch (err) {
    thinkingEl.remove();
    addMessage("agent", `Error: ${err.message}`, true);
  } finally {
    isSending = false;
    sendBtn.disabled = false;
  }
}

function addMessage(role, text, escalate = false, isThinking = false) {
  const div = document.createElement("div");
  div.className = `message ${role}` + (escalate ? " escalate" : "") + (isThinking ? " thinking" : "");
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}
