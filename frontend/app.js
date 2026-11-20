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

async function sendMessage() {
  const message = chatInput.value.trim();
  if (!message || !sessionId) return;
  addMessage("user", message);
  chatInput.value = "";

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
    addMessage("agent", text, data.escalate);
  } catch (err) {
    addMessage("agent", `Error: ${err.message}`, true);
  }
}

function addMessage(role, text, escalate = false) {
  const div = document.createElement("div");
  div.className = `message ${role}` + (escalate ? " escalate" : "");
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}
