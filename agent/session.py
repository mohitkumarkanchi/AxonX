"""
SQLite session persistence — full conversation history, operations, context snapshots.

Schema holds everything needed to resume exactly where we left off:
- sessions table: workspace + branch state
- messages table: every user/assistant message ever
- operations table: every code operation (modify/commit/undo)
- context_snapshots: what RAG retrieved per message
- conversation_summaries: compressed older turns
- token_usage: per-provider spend tracking
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .llm.provider import Message


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------

@dataclass
class Session:
    id: str
    workspace_path: str
    current_branch: str = "main"
    scope_pin: str = ""
    provider: str = "ollama"
    created_at: str = ""
    updated_at: str = ""
    last_active: str = ""
    is_resumed: bool = False


@dataclass
class SessionMessage:
    id: int
    session_id: str
    role: str
    content: str
    agent_type: str = ""
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp: str = ""


@dataclass
class Operation:
    id: str
    session_id: str
    type: str
    instruction: str = ""
    plan: list = field(default_factory=list)
    files_affected: list[str] = field(default_factory=list)
    checkpoint_ref: str = ""
    working_branch: str = ""
    status: str = "pending"
    timestamp: str = ""


@dataclass
class SessionSummary:
    id: str
    workspace_path: str
    current_branch: str
    last_active: str
    message_count: int
    pending_operations: int


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    workspace_path  TEXT NOT NULL,
    current_branch  TEXT NOT NULL DEFAULT 'main',
    scope_pin       TEXT DEFAULT '',
    provider        TEXT DEFAULT 'ollama',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    agent_type      TEXT DEFAULT '',
    provider        TEXT DEFAULT '',
    model           TEXT DEFAULT '',
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operations (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    type            TEXT NOT NULL,
    instruction     TEXT DEFAULT '',
    plan            TEXT DEFAULT '[]',
    files_affected  TEXT DEFAULT '[]',
    checkpoint_ref  TEXT DEFAULT '',
    working_branch  TEXT DEFAULT '',
    status          TEXT DEFAULT 'pending',
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS context_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      INTEGER REFERENCES messages(id),
    chunk_ids       TEXT NOT NULL DEFAULT '[]',
    skill_cards     TEXT DEFAULT '[]',
    graph_symbols   TEXT DEFAULT '[]',
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversation_summaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    covers_from     INTEGER,
    covers_to       INTEGER,
    summary         TEXT NOT NULL,
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS token_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    operation       TEXT DEFAULT '',
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_session  ON messages(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_role     ON messages(session_id, role);
CREATE INDEX IF NOT EXISTS idx_operations_session ON operations(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_context_message   ON context_snapshots(message_id);
CREATE INDEX IF NOT EXISTS idx_summaries_session ON conversation_summaries(session_id);
CREATE INDEX IF NOT EXISTS idx_usage_session     ON token_usage(session_id, provider);
"""

_DB_DIR = Path.home() / ".agent_workspace"


class SessionStore:
    """Full persistent session + conversation + context store."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            _DB_DIR.mkdir(parents=True, exist_ok=True)
            db_path = _DB_DIR / "sessions.db"
        self._path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def get_or_create(
        self,
        workspace_path: str,
        branch: str,
        provider: str = "ollama",
    ) -> Session:
        """Return the most recent session for this workspace+branch, or create a new one."""
        row = self._conn.execute(
            """SELECT * FROM sessions
               WHERE workspace_path = ? AND current_branch = ?
               ORDER BY last_active DESC LIMIT 1""",
            (workspace_path, branch),
        ).fetchone()

        if row:
            session = Session(
                id=row["id"],
                workspace_path=row["workspace_path"],
                current_branch=row["current_branch"],
                scope_pin=row["scope_pin"] or "",
                provider=row["provider"] or provider,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                last_active=row["last_active"],
                is_resumed=True,
            )
            # Touch last_active
            self._conn.execute(
                "UPDATE sessions SET last_active = CURRENT_TIMESTAMP WHERE id = ?",
                (session.id,),
            )
            self._conn.commit()
            return session

        # Create new session
        session_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO sessions(id, workspace_path, current_branch, provider)
               VALUES (?, ?, ?, ?)""",
            (session_id, workspace_path, branch, provider),
        )
        self._conn.commit()
        return Session(
            id=session_id,
            workspace_path=workspace_path,
            current_branch=branch,
            provider=provider,
            is_resumed=False,
        )

    def update_session(
        self,
        session_id: str,
        branch: str | None = None,
        scope_pin: str | None = None,
        provider: str | None = None,
    ) -> None:
        updates = []
        params = []
        if branch is not None:
            updates.append("current_branch = ?")
            params.append(branch)
        if scope_pin is not None:
            updates.append("scope_pin = ?")
            params.append(scope_pin)
        if provider is not None:
            updates.append("provider = ?")
            params.append(provider)
        if not updates:
            return
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(session_id)
        self._conn.execute(
            f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Message persistence
    # ------------------------------------------------------------------

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_type: str = "",
        provider: str = "",
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO messages(session_id, role, content, agent_type,
               provider, model, input_tokens, output_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, role, content, agent_type, provider, model,
             input_tokens, output_tokens),
        )
        self._conn.commit()
        # Track token usage
        if (input_tokens or output_tokens) and provider and model:
            self.record_token_usage(
                session_id, provider, model, input_tokens, output_tokens,
                operation=agent_type,
            )
        return cur.lastrowid

    def load_conversation(
        self,
        session_id: str,
        limit: int = 50,
        summarise_after_turns: int = 8,
        keep_recent_turns: int = 4,
    ) -> list[Message]:
        """
        Load conversation history, substituting old turns with summaries.
        Returns a ready-to-send messages list.
        """
        # Check if we have summaries covering older turns
        summaries = self._conn.execute(
            """SELECT * FROM conversation_summaries
               WHERE session_id = ? ORDER BY covers_to ASC""",
            (session_id,),
        ).fetchall()

        # Get recent raw messages
        recent_rows = self._conn.execute(
            """SELECT * FROM messages WHERE session_id = ?
               ORDER BY id DESC LIMIT ?""",
            (session_id, keep_recent_turns * 2),
        ).fetchall()
        recent_rows = list(reversed(recent_rows))

        messages: list[Message] = []

        # Prepend the latest summary as a system-style context message
        if summaries:
            latest_summary = summaries[-1]
            messages.append(Message(
                role="user",
                content=f"[Previous conversation summary]:\n{latest_summary['summary']}",
            ))
            messages.append(Message(
                role="assistant",
                content="Understood. I'll continue from where we left off.",
            ))

        # Add recent raw messages
        for row in recent_rows:
            if row["role"] in ("user", "assistant"):
                messages.append(Message(role=row["role"], content=row["content"]))

        return messages

    def load_conversation_messages(self, session_id: str, limit: int = 20) -> list[Message]:
        """Simple load of recent raw messages for agent context."""
        rows = self._conn.execute(
            """SELECT role, content FROM messages
               WHERE session_id = ? AND role IN ('user', 'assistant')
               ORDER BY id DESC LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        return [Message(role=r["role"], content=r["content"]) for r in reversed(rows)]

    def get_last_message(self, session_id: str) -> Optional[SessionMessage]:
        row = self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row:
            return SessionMessage(**{k: row[k] for k in row.keys()})
        return None

    # ------------------------------------------------------------------
    # Context snapshots
    # ------------------------------------------------------------------

    def save_context_snapshot(
        self,
        message_id: int,
        chunk_ids: list[str],
        skill_cards: list[str] | None = None,
        graph_symbols: list[str] | None = None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO context_snapshots(message_id, chunk_ids, skill_cards, graph_symbols)
               VALUES (?, ?, ?, ?)""",
            (
                message_id,
                json.dumps(chunk_ids),
                json.dumps(skill_cards or []),
                json.dumps(graph_symbols or []),
            ),
        )
        self._conn.commit()

    def get_context_snapshot(self, message_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM context_snapshots WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if row:
            return {
                "chunk_ids":     json.loads(row["chunk_ids"]),
                "skill_cards":   json.loads(row["skill_cards"]),
                "graph_symbols": json.loads(row["graph_symbols"]),
            }
        return None

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def save_operation(
        self,
        session_id: str,
        type: str,
        instruction: str = "",
        plan: list | None = None,
        files: list[str] | None = None,
        checkpoint_ref: str = "",
        working_branch: str = "",
    ) -> str:
        op_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO operations(id, session_id, type, instruction,
               plan, files_affected, checkpoint_ref, working_branch, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                op_id, session_id, type, instruction,
                json.dumps(plan or []),
                json.dumps(files or []),
                checkpoint_ref,
                working_branch,
            ),
        )
        self._conn.commit()
        return op_id

    def complete_operation(self, operation_id: str) -> None:
        self._conn.execute(
            "UPDATE operations SET status = 'complete' WHERE id = ?",
            (operation_id,),
        )
        self._conn.commit()

    def fail_operation(self, operation_id: str) -> None:
        self._conn.execute(
            "UPDATE operations SET status = 'failed' WHERE id = ?",
            (operation_id,),
        )
        self._conn.commit()

    def rollback_operation(self, operation_id: str) -> None:
        self._conn.execute(
            "UPDATE operations SET status = 'rolled_back' WHERE id = ?",
            (operation_id,),
        )
        self._conn.commit()

    def get_pending_operations(self, session_id: str) -> list[Operation]:
        rows = self._conn.execute(
            """SELECT * FROM operations WHERE session_id = ? AND status = 'pending'
               ORDER BY timestamp""",
            (session_id,),
        ).fetchall()
        return [
            Operation(
                id=r["id"],
                session_id=r["session_id"],
                type=r["type"],
                instruction=r["instruction"],
                plan=json.loads(r["plan"]),
                files_affected=json.loads(r["files_affected"]),
                checkpoint_ref=r["checkpoint_ref"],
                working_branch=r["working_branch"],
                status=r["status"],
                timestamp=r["timestamp"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Conversation summarisation
    # ------------------------------------------------------------------

    def summarise_old_turns(
        self,
        session_id: str,
        provider,   # LLMProvider
        summarise_after_turns: int = 8,
        keep_recent_turns: int = 4,
    ) -> bool:
        """
        Compress older turns into a summary when message count exceeds threshold.
        Returns True if summarisation was performed.
        """
        total = self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role IN ('user','assistant')",
            (session_id,),
        ).fetchone()[0]

        if total <= summarise_after_turns:
            return False

        # Find what's already been summarised
        latest_summary = self._conn.execute(
            """SELECT covers_to FROM conversation_summaries
               WHERE session_id = ? ORDER BY covers_to DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
        summarised_to = latest_summary["covers_to"] if latest_summary else 0

        # Get the messages to summarise (excluding keep_recent_turns)
        to_summarise = self._conn.execute(
            """SELECT id, role, content FROM messages
               WHERE session_id = ? AND id > ? AND role IN ('user', 'assistant')
               ORDER BY id DESC LIMIT ?""",
            (session_id, summarised_to, total - keep_recent_turns),
        ).fetchall()

        if not to_summarise or len(to_summarise) < 2:
            return False

        to_summarise = list(reversed(to_summarise))
        from_id = to_summarise[0]["id"]
        to_id = to_summarise[-1]["id"]

        conversation_text = "\n".join(
            f"{r['role'].upper()}: {r['content'][:500]}" for r in to_summarise
        )

        prompt = (
            "Summarise this conversation in 3-5 sentences, preserving: "
            "key decisions, file names, code changes discussed, unresolved questions.\n\n"
            f"{conversation_text}"
        )

        try:
            from .llm.provider import Message as LLMMessage
            response = provider.chat(
                [LLMMessage(role="user", content=prompt)],
                max_tokens=512,
            )
            summary_text = response.content
        except Exception as exc:
            summary_text = f"[Auto-summary failed: {exc}]"

        self._conn.execute(
            """INSERT INTO conversation_summaries
               (session_id, covers_from, covers_to, summary)
               VALUES (?, ?, ?, ?)""",
            (session_id, from_id, to_id, summary_text),
        )
        self._conn.commit()
        return True

    # ------------------------------------------------------------------
    # Token usage
    # ------------------------------------------------------------------

    def record_token_usage(
        self,
        session_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        operation: str = "",
    ) -> None:
        self._conn.execute(
            """INSERT INTO token_usage(session_id, provider, model,
               input_tokens, output_tokens, operation)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, provider, model, input_tokens, output_tokens, operation),
        )
        self._conn.commit()

    def get_token_usage_report(self, session_id: str) -> dict:
        rows = self._conn.execute(
            """SELECT provider, model,
               SUM(input_tokens) as total_in,
               SUM(output_tokens) as total_out,
               COUNT(*) as calls
               FROM token_usage WHERE session_id = ?
               GROUP BY provider, model""",
            (session_id,),
        ).fetchall()
        return [
            {
                "provider":      r["provider"],
                "model":         r["model"],
                "input_tokens":  r["total_in"],
                "output_tokens": r["total_out"],
                "calls":         r["calls"],
            }
            for r in rows
        ]

    def get_all_token_usage(self) -> dict:
        rows = self._conn.execute(
            """SELECT provider, model,
               SUM(input_tokens) as total_in,
               SUM(output_tokens) as total_out,
               COUNT(*) as calls
               FROM token_usage
               GROUP BY provider, model""",
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Session listing
    # ------------------------------------------------------------------

    def list_sessions(self, workspace_path: str) -> list[SessionSummary]:
        rows = self._conn.execute(
            """SELECT s.*,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) as msg_count,
               (SELECT COUNT(*) FROM operations o WHERE o.session_id = s.id AND o.status = 'pending') as pending_ops
               FROM sessions s
               WHERE s.workspace_path = ?
               ORDER BY s.last_active DESC""",
            (workspace_path,),
        ).fetchall()

        return [
            SessionSummary(
                id=r["id"],
                workspace_path=r["workspace_path"],
                current_branch=r["current_branch"],
                last_active=r["last_active"],
                message_count=r["msg_count"],
                pending_operations=r["pending_ops"],
            )
            for r in rows
        ]

    def delete_session(self, session_id: str) -> None:
        """Delete a session and all associated data."""
        for table in ("token_usage", "conversation_summaries",
                      "context_snapshots", "operations", "messages", "sessions"):
            if table == "context_snapshots":
                # Foreign key via message_id
                msg_ids = [
                    r[0] for r in self._conn.execute(
                        "SELECT id FROM messages WHERE session_id = ?", (session_id,)
                    ).fetchall()
                ]
                if msg_ids:
                    placeholders = ",".join("?" * len(msg_ids))
                    self._conn.execute(
                        f"DELETE FROM context_snapshots WHERE message_id IN ({placeholders})",
                        msg_ids,
                    )
            elif table == "sessions":
                self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            else:
                self._conn.execute(
                    f"DELETE FROM {table} WHERE session_id = ?", (session_id,)
                )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
