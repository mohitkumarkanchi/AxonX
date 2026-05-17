"""
Lightweight HTTP + SSE server for the VS Code sidebar extension.

Runs in a daemon thread alongside the agent chat loop.
Default port: 7070 (configurable via AGENT_SERVER_PORT env var).

API surface:
  GET  /api/status              — workspace, branch, session, index info
  POST /api/chat                — send message; streams response via SSE
  GET  /api/operations          — list pending operations
  POST /api/operations/approve  — approve the current plan
  POST /api/operations/cancel   — cancel the current plan
  GET  /api/usage               — token usage this session
  GET  /api/sessions            — list past sessions
  GET  /api/health              — simple liveness check
"""

from __future__ import annotations

import json
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, parse_qs


DEFAULT_PORT = int(os.environ.get("AGENT_SERVER_PORT", "7070"))


# ------------------------------------------------------------------
# Global agent state — injected by the caller (cli.py)
# ------------------------------------------------------------------

class AgentState:
    """Mutable shared state the server reads from and writes to."""

    def __init__(self) -> None:
        self.workspace: str = ""
        self.branch: str = "main"
        self.provider: str = "ollama"
        self.session_id: str = ""
        self.index_status: dict = {}
        self.pending_plan: dict | None = None   # current CodeAct plan awaiting approval
        self.approval_event: threading.Event = threading.Event()
        self.approval_result: str = ""          # "yes" | "cancel"
        self.chat_fn: Callable[[str], None] | None = None  # inject_message(text)
        self.response_queues: list[queue.Queue] = []  # SSE subscribers
        self._lock = threading.Lock()

    def broadcast(self, event: str, data: dict) -> None:
        """Push a SSE message to all connected sidebar clients."""
        msg = _sse_frame(event, data)
        with self._lock:
            dead: list[queue.Queue] = []
            for q in self.response_queues:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self.response_queues.remove(q)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self.response_queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self.response_queues:
                self.response_queues.remove(q)


# Singleton — populated by cli.py before server starts
state = AgentState()


# ------------------------------------------------------------------
# Request handler
# ------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence access log

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/health":
            self._json({"ok": True})
        elif path == "/api/status":
            self._handle_status()
        elif path == "/api/operations":
            self._handle_operations()
        elif path == "/api/usage":
            self._handle_usage()
        elif path == "/api/sessions":
            self._handle_sessions()
        elif path == "/api/stream":
            self._handle_stream()
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        body = self._read_body()

        if path == "/api/chat":
            self._handle_chat(body)
        elif path == "/api/operations/approve":
            self._handle_approve()
        elif path == "/api/operations/cancel":
            self._handle_cancel()
        else:
            self.send_error(404)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _handle_status(self):
        self._json({
            "workspace":    state.workspace,
            "branch":       state.branch,
            "provider":     state.provider,
            "session_id":   state.session_id,
            "index_status": state.index_status,
            "has_plan":     state.pending_plan is not None,
        })

    def _handle_chat(self, body: dict):
        message = body.get("message", "").strip()
        if not message:
            self.send_error(400, "Missing message")
            return

        if state.chat_fn is None:
            self._json({"error": "Agent not initialised"}, status=503)
            return

        # Fire message injection in a thread so we can return 202 immediately
        def _dispatch():
            try:
                state.chat_fn(message)
            except Exception as exc:
                state.broadcast("error", {"message": str(exc)})

        threading.Thread(target=_dispatch, daemon=True).start()
        self._json({"status": "queued"}, status=202)

    def _handle_operations(self):
        plan = state.pending_plan
        self._json({"plan": plan, "has_plan": plan is not None})

    def _handle_approve(self):
        state.approval_result = "yes"
        state.approval_event.set()
        self._json({"status": "approved"})

    def _handle_cancel(self):
        state.approval_result = "cancel"
        state.approval_event.set()
        self._json({"status": "cancelled"})

    def _handle_usage(self):
        from .session import SessionStore
        try:
            store = SessionStore()
            rows = store.get_token_usage_report(state.session_id) if state.session_id else []
            self._json({"usage": rows})
        except Exception as exc:
            self._json({"usage": [], "error": str(exc)})

    def _handle_sessions(self):
        from .session import SessionStore
        try:
            store = SessionStore()
            sessions = store.list_sessions(state.workspace)
            self._json({
                "sessions": [
                    {
                        "id":                s.id,
                        "branch":            s.current_branch,
                        "last_active":       s.last_active,
                        "message_count":     s.message_count,
                        "pending_operations": s.pending_operations,
                    }
                    for s in sessions
                ]
            })
        except Exception as exc:
            self._json({"sessions": [], "error": str(exc)})

    def _handle_stream(self):
        """SSE endpoint — client keeps connection open, receives real-time events."""
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q = state.subscribe()
        try:
            # Send initial status
            frame = _sse_frame("status", {
                "workspace": state.workspace,
                "branch":    state.branch,
                "provider":  state.provider,
            })
            self.wfile.write(frame)
            self.wfile.flush()

            while True:
                try:
                    msg: bytes = q.get(timeout=25)
                    self.wfile.write(msg)
                    self.wfile.flush()
                except queue.Empty:
                    # Heartbeat to keep connection alive
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            state.unsubscribe(q)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Cache-Control, Connection, Accept")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return {}


def _sse_frame(event: str, data: dict) -> bytes:
    payload = json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n".encode()


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def start_server(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Start the HTTP server in a daemon thread. Returns the server instance."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="agent-server")
    t.start()
    return server


def is_port_available(port: int = DEFAULT_PORT) -> bool:
    """Return True if port is not already in use."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def get_port() -> int:
    return DEFAULT_PORT
