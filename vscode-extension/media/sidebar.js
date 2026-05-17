/* Sidebar webview script — vanilla JS, no bundler */
(function () {
  "use strict";

  const vscode = acquireVsCodeApi();
  const PORT = window.AGENT_PORT || "7070";

  // DOM refs
  const messagesEl   = document.getElementById("messages");
  const inputEl      = document.getElementById("input");
  const btnSend      = document.getElementById("btn-send");
  const btnApprove   = document.getElementById("btn-approve");
  const btnCancel    = document.getElementById("btn-cancel");
  const planPanel    = document.getElementById("plan-panel");
  const planContent  = document.getElementById("plan-content");
  const thinkingEl   = document.getElementById("thinking");
  const statusDot    = document.getElementById("status-dot");
  const statusText   = document.getElementById("status-text");
  const branchLabel  = document.getElementById("branch-label");
  const providerLabel= document.getElementById("provider-label");

  // -------------------------------------------------------------------------
  // SSE — real-time stream from agent server
  // -------------------------------------------------------------------------

  let sse = null;
  let reconnectTimer = null;
  let agentMsgBuffer = "";   // accumulate streaming tokens into one bubble
  let agentBubble = null;    // the current in-progress agent message element

  function connectSSE() {
    if (sse) sse.close();
    sse = new EventSource(`http://127.0.0.1:${PORT}/api/stream`);

    sse.addEventListener("status", (e) => {
      const data = JSON.parse(e.data);
      setStatus("connected", data.workspace || "");
      if (data.branch)   branchLabel.textContent   = data.branch;
      if (data.provider) providerLabel.textContent = data.provider;
    });

    sse.addEventListener("token", (e) => {
      const { text } = JSON.parse(e.data);
      setThinking(false);
      if (!agentBubble) {
        agentBubble = appendMessage("agent", "");
      }
      agentMsgBuffer += text;
      agentBubble.innerHTML = renderMarkdown(agentMsgBuffer);
      scrollToBottom();
    });

    sse.addEventListener("message_done", () => {
      agentBubble = null;
      agentMsgBuffer = "";
      setBusy(false);
    });

    sse.addEventListener("plan", (e) => {
      const data = JSON.parse(e.data);
      showPlan(data);
      setBusy(false);
    });

    sse.addEventListener("plan_done", () => {
      hidePlan();
    });

    sse.addEventListener("error", (e) => {
      try {
        const data = JSON.parse(e.data);
        appendMessage("error", data.message || "Unknown error");
      } catch {
        // non-JSON error frame — ignore
      }
      setBusy(false);
    });

    sse.addEventListener("index_progress", (e) => {
      const data = JSON.parse(e.data);
      updateStatus(`Indexing… ${data.done}/${data.total}`);
    });

    sse.addEventListener("index_done", (e) => {
      const data = JSON.parse(e.data);
      updateStatus(`Index ready — ${data.chunks} chunks`);
    });

    sse.onerror = () => {
      setStatus("disconnected", "");
      sse.close();
      sse = null;
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connectSSE, 3000);
    };
  }

  connectSSE();

  // Fetch initial status once on load
  vscode.postMessage({ command: "getStatus" });

  // -------------------------------------------------------------------------
  // VS Code → webview messages
  // -------------------------------------------------------------------------

  window.addEventListener("message", (event) => {
    const msg = event.data;
    switch (msg.type) {
      case "serverStatus":
        if (msg.status === "connected") {
          setStatus("connected", "");
          connectSSE();
        } else if (msg.status === "connecting") {
          setStatus("connecting", "");
        } else {
          setStatus("disconnected", "");
        }
        break;
      case "status":
        updateStatusFromPayload(msg.data);
        break;
      case "error":
        appendMessage("error", msg.message);
        setBusy(false);
        break;
    }
  });

  // -------------------------------------------------------------------------
  // Send message
  // -------------------------------------------------------------------------

  function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;
    appendMessage("user", text);
    inputEl.value = "";
    setBusy(true);
    setThinking(true);
    vscode.postMessage({ command: "sendMessage", text });
  }

  btnSend.addEventListener("click", sendMessage);

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      sendMessage();
    }
  });

  // -------------------------------------------------------------------------
  // Plan approval
  // -------------------------------------------------------------------------

  btnApprove.addEventListener("click", () => {
    hidePlan();
    vscode.postMessage({ command: "approve" });
    setBusy(true);
    setThinking(true);
  });

  btnCancel.addEventListener("click", () => {
    hidePlan();
    vscode.postMessage({ command: "cancel" });
  });

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  function appendMessage(role, text) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    div.innerHTML = renderMarkdown(text);
    messagesEl.appendChild(div);
    scrollToBottom();
    return div;
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setBusy(busy) {
    btnSend.disabled = busy;
    inputEl.disabled = busy;
    if (!busy) setThinking(false);
  }

  function setThinking(show) {
    thinkingEl.classList.toggle("hidden", !show);
    if (show) scrollToBottom();
  }

  function showPlan(data) {
    planContent.textContent = JSON.stringify(data, null, 2);
    planPanel.classList.remove("hidden");
    scrollToBottom();
  }

  function hidePlan() {
    planPanel.classList.add("hidden");
  }

  function setStatus(state, workspace) {
    statusDot.className = `dot ${state}`;
    const labels = { connected: "Connected", connecting: "Connecting…", disconnected: "Offline" };
    statusText.textContent = workspace
      ? `${labels[state] || state} — ${shortenPath(workspace)}`
      : labels[state] || state;
  }

  function updateStatus(text) {
    statusText.textContent = text;
  }

  function updateStatusFromPayload(data) {
    if (data.branch)   branchLabel.textContent   = data.branch;
    if (data.provider) providerLabel.textContent = data.provider;
    if (data.workspace) setStatus("connected", data.workspace);
    if (data.has_plan)  {
      vscode.postMessage({ command: "getStatus" });
    }
  }

  function shortenPath(p) {
    const parts = p.replace(/\\/g, "/").split("/");
    return parts.slice(-2).join("/");
  }

  // Minimal markdown renderer: code blocks, inline code, bold, italic
  function renderMarkdown(text) {
    return text
      // Escape HTML first
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      // Fenced code blocks
      .replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
        `<pre><code class="lang-${lang}">${code.trimEnd()}</code></pre>`
      )
      // Inline code
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      // Bold
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      // Italic
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      // Line breaks
      .replace(/\n/g, "<br>");
  }
})();
