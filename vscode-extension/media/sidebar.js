/* Sidebar webview script — vanilla JS, no bundler */
(function () {
  "use strict";

  const vscode = acquireVsCodeApi();
  const PORT = document.body.getAttribute("data-port") || "7070";
  const SERVER_URL = `http://127.0.0.1:${PORT}`;

  // DOM refs
  const messagesEl      = document.getElementById("messages");
  const inputEl         = document.getElementById("input");
  const btnSend         = document.getElementById("btn-send");
  const btnApprove      = document.getElementById("btn-approve");
  const btnCancel       = document.getElementById("btn-cancel");
  const planPanel       = document.getElementById("plan-panel");
  const planContent     = document.getElementById("plan-content");
  const thinkingEl      = document.getElementById("thinking");
  const statusDot       = document.getElementById("status-dot");
  const statusText      = document.getElementById("status-text");
  const branchLabel     = document.getElementById("branch-label");
  const providerLabel   = document.getElementById("provider-label");
  const workspaceNameEl = document.getElementById("workspace-name");
  const btnInterrupt    = document.getElementById("btn-interrupt");
  
  // Indexing progress DOM refs
  const indexContainer  = document.getElementById("index-container");
  const indexRatio      = document.getElementById("index-ratio");
  const indexProgress   = document.getElementById("index-progress-fill");

  // -------------------------------------------------------------------------
  // Auto-resize input textarea
  // -------------------------------------------------------------------------
  inputEl.addEventListener("input", () => {
    inputEl.style.height = "auto";
    inputEl.style.height = (inputEl.scrollHeight) + "px";
  });

  // -------------------------------------------------------------------------
  // Event Delegation (Copy Code & Open Clickable Files)
  // -------------------------------------------------------------------------
  messagesEl.addEventListener("click", (e) => {
    // 1. Copy Code Button Click
    const copyBtn = e.target.closest(".btn-copy-code");
    if (copyBtn) {
      const base64Code = copyBtn.getAttribute("data-code");
      if (base64Code) {
        try {
          const code = decodeURIComponent(escape(atob(base64Code)));
          navigator.clipboard.writeText(code).then(() => {
            const originalText = copyBtn.textContent;
            copyBtn.textContent = "Copied!";
            copyBtn.classList.add("copied");
            setTimeout(() => {
              copyBtn.textContent = originalText;
              copyBtn.classList.remove("copied");
            }, 2000);
          });
        } catch (err) {
          console.error("Failed to copy code: ", err);
        }
      }
      return;
    }

    // 2. Clickable File Tag Click (Opens in Editor)
    const fileTag = e.target.closest(".file-tag");
    if (fileTag) {
      const filePath = fileTag.getAttribute("data-filepath");
      if (filePath) {
        vscode.postMessage({ command: "openFile", filePath });
      }
    }
  });

  // -------------------------------------------------------------------------
  // Native EventSource — Direct streaming to the Python server!
  // -------------------------------------------------------------------------

  let agentMsgBuffer = "";   // accumulate streaming tokens into one bubble
  let agentBubble = null;    // the current in-progress agent message element
  let sseSource = null;

  function connectSSE() {
    if (sseSource) {
      sseSource.close();
    }

    sseSource = new EventSource(`${SERVER_URL}/api/stream`);

    sseSource.addEventListener("status", (e) => {
      try {
        const data = JSON.parse(e.data);
        setStatus("connected", data.workspace || "");
        updateStatusFromPayload(data);
      } catch (err) {
        console.error("Error parsing status SSE: ", err);
      }
    });

    sseSource.addEventListener("user_message", (e) => {
      try {
        const data = JSON.parse(e.data);
        // User message echoed by server — already drawn, so noop
      } catch (err) {
        console.error(err);
      }
    });

    sseSource.addEventListener("assistant_message", (e) => {
      try {
        const data = JSON.parse(e.data);
        setThinking(false);
        
        // Append the assistant's message bubble
        const bubble = appendMessage(data.agent || "agent", data.content);
        
        // If there are context citations, render them!
        if (data.citations && data.citations.length > 0) {
          const citationsDiv = document.createElement("div");
          citationsDiv.className = "citations-container";
          
          const tags = data.citations.map(c => {
            const fp = c.filepath || c;
            const range = c.start_line ? `:${c.start_line}` : "";
            const label = `${fp}${range}`;
            return `<span class="file-tag" data-filepath="${fp}" title="Click to open ${fp}">📄 ${label}</span>`;
          }).join(" ");
          
          citationsDiv.innerHTML = `<div class="citations-header">📚 Context Citations:</div>` + tags;
          bubble.appendChild(citationsDiv);
        }
        
        setBusy(false);
      } catch (err) {
        console.error("Error parsing assistant message SSE: ", err);
        setBusy(false);
      }
    });

    sseSource.addEventListener("plan", (e) => {
      try {
        const data = JSON.parse(e.data);
        showPlan(data);
        setBusy(false);
      } catch (err) {
        console.error("Error parsing plan SSE: ", err);
      }
    });

    sseSource.addEventListener("plan_cleared", () => {
      hidePlan();
      setBusy(false);
    });

    sseSource.addEventListener("error", (e) => {
      if (!e || !e.data) return; // Ignore generic browser network errors (handled by onerror)
      try {
        const data = JSON.parse(e.data);
        appendMessage("error", data.message || "Unknown error");
        setBusy(false);
      } catch (err) {
        console.error("Error parsing error SSE: ", err);
      }
    });

    sseSource.addEventListener("index_progress", (e) => {
      try {
        const data = JSON.parse(e.data);
        indexContainer.classList.remove("hidden");
        const ratio = data.total > 0 ? Math.round((data.done / data.total) * 100) : 0;
        indexRatio.textContent = `${ratio}%`;
        indexProgress.style.width = `${ratio}%`;
        updateStatus(`Indexing… ${data.done}/${data.total}`);
      } catch (err) {
        console.error("Error parsing index SSE: ", err);
      }
    });

    sseSource.addEventListener("index_done", (e) => {
      try {
        const data = JSON.parse(e.data);
        indexRatio.textContent = "100%";
        indexProgress.style.width = "100%";
        updateStatus(`Index ready — ${data.chunks} chunks`);
        setTimeout(() => {
          indexContainer.classList.add("hidden");
        }, 3000);
      } catch (err) {
        console.error("Error parsing index_done SSE: ", err);
      }
    });

    sseSource.onerror = () => {
      setStatus("disconnected");
      setTimeout(() => connectSSE(), 3000);
    };
  }

  // -------------------------------------------------------------------------
  // Send message — Direct fetch POST to the server!
  // -------------------------------------------------------------------------

  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;
    appendMessage("user", text);
    inputEl.value = "";
    inputEl.style.height = "40px"; // reset input height
    setBusy(true);
    setThinking(true);

    try {
      const res = await fetch(`${SERVER_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) {
        appendMessage("error", `Server returned error status: ${res.status}`);
        setBusy(false);
      }
    } catch (err) {
      appendMessage("error", `Could not reach agent server: ${err}`);
      setBusy(false);
    }
  }

  btnSend.addEventListener("click", sendMessage);

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // -------------------------------------------------------------------------
  // Interrupt Button — POST to cancel endpoint!
  // -------------------------------------------------------------------------
  btnInterrupt.addEventListener("click", async () => {
    try {
      await fetch(`${SERVER_URL}/api/operations/cancel`, { method: "POST" });
      appendMessage("error", "Generation interrupted by user.");
      setBusy(false);
    } catch (err) {
      console.error("Failed to interrupt operation: ", err);
    }
  });

  // -------------------------------------------------------------------------
  // Plan approvals — Direct fetch POST to the server!
  // -------------------------------------------------------------------------

  btnApprove.addEventListener("click", async () => {
    hidePlan();
    setBusy(true);
    setThinking(true);
    try {
      await fetch(`${SERVER_URL}/api/operations/approve`, { method: "POST" });
    } catch (err) {
      appendMessage("error", `Failed to approve changes: ${err}`);
      setBusy(false);
    }
  });

  btnCancel.addEventListener("click", async () => {
    hidePlan();
    try {
      await fetch(`${SERVER_URL}/api/operations/cancel`, { method: "POST" });
    } catch (err) {
      appendMessage("error", `Failed to cancel changes: ${err}`);
    }
  });

  // -------------------------------------------------------------------------
  // Fetch initial status — Direct fetch GET from the server!
  // -------------------------------------------------------------------------
  async function fetchInitialStatus() {
    try {
      const res = await fetch(`${SERVER_URL}/api/status`);
      if (res.ok) {
        const data = await res.json();
        setStatus("connected", data.workspace || "");
        updateStatusFromPayload(data);
      }
    } catch (err) {
      console.log("Offline or server not ready yet.");
    }
  }

  // Initial call & SSE stream trigger
  fetchInitialStatus();
  connectSSE();

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
    if (!data) return;
    
    let html = `
      <div class="plan-summary-card">
        <div class="plan-section-title">📝 Summary</div>
        <div class="plan-summary-text">${data.summary || "No summary provided"}</div>
      </div>
    `;
    
    if (data.files && data.files.length > 0) {
      html += `
        <div class="plan-section-title">📂 Files to Modify</div>
        <div class="plan-files-list">
          ${data.files.map(f => `
            <div class="plan-file-item">
              <span class="file-icon">📄</span>
              <span class="file-name">${f}</span>
              <span class="change-badge modify">MODIFY</span>
            </div>
          `).join("")}
        </div>
      `;
    }
    
    if (data.steps && data.steps.length > 0) {
      html += `
        <div class="plan-section-title">🪜 Implementation Steps</div>
        <div class="plan-steps-list">
          ${data.steps.map((s, idx) => `
            <div class="plan-step-item">
              <div class="step-num">${idx + 1}</div>
              <div class="step-details">
                <div class="step-file">${s.file || "Workspace"}</div>
                <div class="step-desc">${s.description || s.step}</div>
              </div>
            </div>
          `).join("")}
        </div>
      `;
    }
    
    planContent.innerHTML = html;
    planPanel.classList.remove("hidden");
    scrollToBottom();
  }

  function hidePlan() {
    planPanel.classList.add("hidden");
  }

  function setStatus(state, workspace) {
    statusDot.className = `dot ${state}`;
    const labels = { connected: "Connected", connecting: "Connecting…", disconnected: "Offline" };
    
    if (workspace) {
      workspaceNameEl.textContent = shortenPath(workspace);
      statusText.textContent = labels[state] || state;
    } else {
      statusText.textContent = labels[state] || state;
    }
  }

  function updateStatus(text) {
    statusText.textContent = text;
  }

  function updateStatusFromPayload(data) {
    if (data.branch) {
      branchLabel.textContent = data.branch;
      branchLabel.classList.remove("hidden");
    }
    if (data.provider) {
      providerLabel.textContent = data.provider;
      providerLabel.classList.remove("hidden");
    }
    if (data.workspace) setStatus("connected", data.workspace);
    if (data.has_plan)  {
      fetchInitialStatus();
    }
  }

  function shortenPath(p) {
    const parts = p.replace(/\\/g, "/").split("/");
    return parts.slice(-1)[0] || "workspace";
  }

  // -------------------------------------------------------------------------
  // Premium, High-Fidelity Markdown Line-by-Line Renderer
  // -------------------------------------------------------------------------
  function renderMarkdown(text) {
    if (!text) return "";

    // Escape HTML to prevent XSS
    let escaped = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // 1. Process fenced code blocks first
    const codeBlocks = [];
    escaped = escaped.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
      const placeholder = `__CODE_BLOCK_${codeBlocks.length}__`;
      const base64Code = btoa(unescape(encodeURIComponent(code.trimEnd())));
      codeBlocks.push(`
        <div class="code-block-wrapper">
          <div class="code-block-header">
            <span class="code-lang">${lang || "code"}</span>
            <button class="btn-copy-code" data-code="${base64Code}">Copy</button>
          </div>
          <pre><code class="lang-${lang}">${code.trimEnd()}</code></pre>
        </div>
      `);
      return placeholder;
    });

    const lines = escaped.split("\n");
    let inList = false;
    let inOrderedList = false;
    const processedLines = [];

    for (let line of lines) {
      let trimmed = line.trim();

      // Unordered list items starting with "-", "*", "+"
      if (trimmed.startsWith("- ") || trimmed.startsWith("* ") || trimmed.startsWith("+ ")) {
        if (!inList) {
          processedLines.push("<ul>");
          inList = true;
        }
        if (inOrderedList) {
          processedLines.push("</ol>");
          inOrderedList = false;
        }
        const content = trimmed.substring(2);
        processedLines.push(`<li>${content}</li>`);
        continue;
      }

      // Ordered list items (e.g. "1. item")
      const olMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
      if (olMatch) {
        if (!inOrderedList) {
          processedLines.push("<ol>");
          inOrderedList = true;
        }
        if (inList) {
          processedLines.push("</ul>");
          inList = false;
        }
        const content = olMatch[2];
        processedLines.push(`<li>${content}</li>`);
        continue;
      }

      // Close open lists if we hit a blank line
      if (inList && trimmed === "") {
        processedLines.push("</ul>");
        inList = false;
      }
      if (inOrderedList && trimmed === "") {
        processedLines.push("</ol>");
        inOrderedList = false;
      }

      // Headers
      if (trimmed.startsWith("### ")) {
        processedLines.push(`<h3>${trimmed.substring(4)}</h3>`);
      } else if (trimmed.startsWith("## ")) {
        processedLines.push(`<h2>${trimmed.substring(3)}</h2>`);
      } else if (trimmed.startsWith("# ")) {
        processedLines.push(`<h1>${trimmed.substring(2)}</h1>`);
      } else if (trimmed === "---") {
        processedLines.push("<hr class='markdown-hr' />");
      } else {
        processedLines.push(line);
      }
    }

    // Close lists at the end
    if (inList) processedLines.push("</ul>");
    if (inOrderedList) processedLines.push("</ol>");

    let html = processedLines.join("\n");

    // Replace code block placeholders back
    for (let i = 0; i < codeBlocks.length; i++) {
      html = html.replace(`__CODE_BLOCK_${i}__`, codeBlocks[i]);
    }

    // Inline formatting: Bold, Italic, Clickable Files, standard Inline Code, Line breaks
    html = html
      .replace(/`([^`\n]+)`/g, (_, code) => {
        // If the code string looks like a file path or contains common file extensions, make it clickable!
        const isFile = /\.(ts|js|css|html|py|json|md|toml|sh|yml|yaml|rs|go|c|cpp|h)$/i.test(code) || code.includes("/");
        if (isFile) {
          return `<span class="file-tag" data-filepath="${code.trim()}" title="Click to open ${code.trim()} in VS Code">📄 ${code.trim()}</span>`;
        }
        return `<code>${code}</code>`;
      })
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/\n/g, "<br>");

    return html;
  }
})();
