# AxonX VS Code Integration

AxonX comes with a native **VS Code Extension** that hooks directly into the underlying code intelligence engine, exposing a real-time sidebar interface for conversational coding, plan approvals, and codebase navigation.

---

## 🔌 Core Integration Mechanism

The integration operates as a decoupled **Client-Server Architecture** running over a local loopback port (`http://127.0.0.1:7070`):

```
┌──────────────────────────────────────┐          ┌───────────────────────────┐
│          VS Code Editor              │          │       AxonX Daemon        │
│                                      │          │                           │
│  ┌────────────────────────────────┐  │          │  ┌─────────────────────┐  │
│  │   Webview Sidebar Panel        │  │          │  │  HTTP + SSE Server  │  │
│  │                                │  │          │  │                     │  │
│  │   - Real-time Chat UI          │  │   POST   │  │  - `/api/chat`      │  │
│  │   - SSE Event Handler          ├──┼─────────►│  │  - `/api/stream`    │  │
│  │   - Plan Approve/Cancel        │  │          │  │                     │  │
│  └────────────────────────────────┘  │  Stream  │  └─────────────────────┘  │
│                                      │◄─ ─ ─ ─ ─│                           │
│  ┌────────────────────────────────┐  │   (SSE)  │  ┌─────────────────────┐  │
│  │   Extension Host Code          │  │          │  │  CodeAct/RAG Core   │  │
│  │                                │  │          │  │                     │  │
│  │   - Auto-starts `axonx serve`  │  │          │  │  - Vector/Graph     │  │
│  │   - Monitors status bar        │  │          │  │  - Git Checkpoints  │  │
│  └────────────────────────────────┘  │          │  └─────────────────────┘  │
└──────────────────────────────────────┘          └───────────────────────────┘
```

---

## ⚡ The Event Stream Protocol (SSE)

Instead of using heavy, resource-intensive WebSockets, AxonX leverages **Server-Sent Events (SSE)** via a standard-library SSE endpoint (`GET /api/stream`). This guarantees:
1. **Low Latency:** Instantaneous, single-direction word-by-word token streaming from local LLMs.
2. **Robustness:** Native reconnection handling managed automatically by the browser/webview.
3. **Simplicity:** Zero socket handshakes, running over pure HTTP.

### Stream Event Types
* `token` - Real-time word/token stream for assistant responses.
* `plan` - Structured JSON containing code modification diff steps.
* `index_progress` - Status updates on seed or incremental indexing.
* `error` - Runtime execution error reports.

---

## 🛠️ Sidebar Features

### 1. Real-Time Chat & Token Streaming
The sidebar panel contains an interactive chat area. When you submit a question:
* The input is POSTed to `http://localhost:7070/api/chat`.
* The server processes the query using the **Orchestrator** (classifying routing/reasoning/coding).
* Tokens are streamed immediately back to the sidebar HTML webview.

### 2. Surgical Plan Approval Panel
When AxonX proposes a code modification (e.g. `axonx modify` trigger):
* The agent formats the modification as a precise, structured replacement diff.
* The server sends a `plan` event containing the affected files and diff segments.
* The VS Code Webview renders a beautiful, tabular **Approve / Cancel Plan Panel** showing:
  * Affected file names.
  * Description of proposed changes.
  * A green **Approve Change** button (triggers `POST /api/operations/approve`).
  * A red **Cancel Change** button (triggers `POST /api/operations/cancel`).
* This enables the developer to visually inspect proposed changes and authorize commits instantly without leaving their keyboard.

### 3. Status Bar Watchdog
The extension monitors the connection state of the background AxonX server.
* Displays a **`$(sync~spin) AxonX: Indexing`** indicator when files are being chunked or updated in the background.
* Displays the active **git branch** and **LLM provider** inside the VS Code status bar for absolute visibility.
