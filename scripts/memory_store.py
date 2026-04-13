from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CODEX_HOME = Path.home() / ".codex"
SESSION_ROOT = CODEX_HOME / "sessions"
STATE_DIR = CODEX_HOME / "memories" / "codex-mem"
DB_PATH = STATE_DIR / "memory.sqlite3"

MAX_MESSAGE_TEXT = 8000
MAX_AGGREGATE_TEXT = 200000
MAX_SUMMARY_TEXT = 1200
TITLE_FALLBACK = "Untitled session"

WHITESPACE_RE = re.compile(r"\s+")
ENV_BLOCK_RE = re.compile(r"<environment_context>.*?</environment_context>", re.DOTALL)
XML_TAG_RE = re.compile(r"</?[^>]+>")


@dataclass
class ParsedSession:
    session_id: str
    file_path: str
    modified_ns: int
    size_bytes: int
    started_at: str
    cwd: str
    source: str
    model: str
    title: str
    summary: str
    tool_names: list[str]
    message_text: str
    messages: list[dict[str, str]]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collapse_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def trim_text(text: str, limit: int) -> str:
    value = collapse_whitespace(text)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def clean_user_text(text: str) -> str:
    cleaned = ENV_BLOCK_RE.sub(" ", text)
    cleaned = XML_TAG_RE.sub(" ", cleaned)
    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# Context from my IDE setup:"):
            continue
        if line.startswith("## Active file:"):
            continue
        if line.startswith("## Open tabs:"):
            continue
        if line.startswith("## My request for Codex:"):
            continue
        if line.startswith("<cwd>") or line.startswith("<shell>"):
            continue
        if line.startswith("<approval_policy>") or line.startswith("<sandbox_mode>"):
            continue
        if line.startswith("<network_access>") or line.startswith("</environment_context>"):
            continue
        lines.append(line)
    return collapse_whitespace(" ".join(lines))


def unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def connect_db() -> sqlite3.Connection:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    initialize_db(conn)
    return conn


def initialize_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            file_path TEXT NOT NULL UNIQUE,
            modified_ns INTEGER NOT NULL,
            size_bytes INTEGER NOT NULL,
            started_at TEXT,
            cwd TEXT,
            source TEXT,
            model TEXT,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            tool_names TEXT NOT NULL,
            message_text TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            timestamp TEXT,
            role TEXT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sessions_cwd ON sessions(cwd);
        CREATE INDEX IF NOT EXISTS idx_messages_session_ordinal ON messages(session_id, ordinal);
        """
    )

    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(
                session_id UNINDEXED,
                title,
                summary,
                cwd,
                tool_names,
                message_text
            );
            """
        )
    except sqlite3.OperationalError:
        pass


def fts_available(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'session_fts'"
    ).fetchone()
    return row is not None


def iter_session_files() -> list[Path]:
    if not SESSION_ROOT.exists():
        return []
    return sorted(SESSION_ROOT.rglob("*.jsonl"))


def extract_content_texts(content: Any) -> list[str]:
    texts: list[str] = []
    if not isinstance(content, list):
        return texts
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type in {"input_text", "output_text", "summary_text"}:
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
        elif part_type == "refusal":
            text = part.get("refusal")
            if isinstance(text, str) and text.strip():
                texts.append(text)
    return texts


def append_message(
    messages: list[dict[str, str]],
    role: str,
    kind: str,
    text: str,
    timestamp: str,
) -> None:
    cleaned = trim_text(text, MAX_MESSAGE_TEXT)
    if not cleaned:
        return
    if messages:
        last = messages[-1]
        if last["role"] == role and last["kind"] == kind and last["text"] == cleaned:
            return
    messages.append(
        {
            "timestamp": timestamp or "",
            "role": role,
            "kind": kind,
            "text": cleaned,
        }
    )


def parse_session_file(path: Path) -> ParsedSession | None:
    session_id = path.stem.replace("rollout-", "")
    started_at = ""
    cwd = ""
    source = ""
    model = ""
    tool_names: list[str] = []
    messages: list[dict[str, str]] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            timestamp = record.get("timestamp", "")
            record_type = record.get("type")
            payload = record.get("payload", {})

            if record_type == "session_meta":
                session_id = payload.get("id") or session_id
                started_at = payload.get("timestamp") or timestamp or started_at
                cwd = payload.get("cwd") or cwd
                source = payload.get("source") or payload.get("originator") or source
                model = payload.get("model") or payload.get("model_provider") or model
                continue

            if record_type == "turn_context":
                cwd = payload.get("cwd") or cwd
                model = payload.get("model") or model
                continue

            if record_type == "response_item" and isinstance(payload, dict):
                item_type = payload.get("type")
                if item_type == "message":
                    role = payload.get("role") or "unknown"
                    if role not in {"user", "assistant"}:
                        continue
                    text = "\n".join(extract_content_texts(payload.get("content")))
                    if role == "user":
                        text = clean_user_text(text)
                    append_message(messages, role, "message", text, timestamp)
                elif item_type == "reasoning":
                    summary = "\n".join(extract_content_texts(payload.get("summary")))
                    append_message(messages, "assistant", "reasoning", summary, timestamp)
                elif item_type == "function_call":
                    name = str(payload.get("name") or "tool")
                    arguments = str(payload.get("arguments") or "")
                    tool_names.append(name)
                    append_message(
                        messages,
                        "tool",
                        "tool_call",
                        f"{name}: {arguments}",
                        timestamp,
                    )
                elif item_type == "function_call_output":
                    output = str(payload.get("output") or "")
                    append_message(messages, "tool", "tool_output", output, timestamp)
                elif item_type == "custom_tool_call":
                    name = str(payload.get("name") or "custom_tool")
                    tool_names.append(name)
                elif item_type == "custom_tool_call_output":
                    output = str(payload.get("output") or "")
                    append_message(messages, "tool", "tool_output", output, timestamp)
                continue

            if record_type == "event_msg" and isinstance(payload, dict):
                event_type = payload.get("type")
                if event_type == "agent_reasoning":
                    append_message(
                        messages,
                        "assistant",
                        "reasoning",
                        str(payload.get("text") or ""),
                        timestamp,
                    )

    if not started_at:
        started_at = datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat()

    meaningful_user_messages = [
        message["text"]
        for message in messages
        if message["role"] == "user" and message["text"]
    ]
    title_source = meaningful_user_messages[0] if meaningful_user_messages else ""
    title = trim_text(title_source, 120) if title_source else ""
    if not title:
        title = Path(cwd).name if cwd else TITLE_FALLBACK
    if not title:
        title = TITLE_FALLBACK

    assistant_messages = [
        message["text"]
        for message in messages
        if message["role"] == "assistant" and message["kind"] == "message"
    ]
    tool_names = unique_preserve_order(tool_names)

    summary_parts: list[str] = []
    if meaningful_user_messages:
        summary_parts.append(f"Request: {trim_text(meaningful_user_messages[0], 350)}")
    if tool_names:
        summary_parts.append(f"Tools: {', '.join(tool_names[:8])}")
    if assistant_messages:
        summary_parts.append(f"Outcome: {trim_text(assistant_messages[-1], 350)}")
    summary = trim_text(" | ".join(summary_parts), MAX_SUMMARY_TEXT)

    aggregate_lines = [
        f"{message['role']}[{message['kind']}]: {message['text']}" for message in messages
    ]
    message_text = trim_text("\n".join(aggregate_lines), MAX_AGGREGATE_TEXT)

    stat = path.stat()
    return ParsedSession(
        session_id=session_id,
        file_path=str(path),
        modified_ns=stat.st_mtime_ns,
        size_bytes=stat.st_size,
        started_at=started_at,
        cwd=cwd,
        source=source,
        model=model,
        title=title,
        summary=summary,
        tool_names=tool_names,
        message_text=message_text,
        messages=messages,
    )


def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    if not session_id:
        return
    if fts_available(conn):
        conn.execute("DELETE FROM session_fts WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def upsert_session(conn: sqlite3.Connection, parsed: ParsedSession) -> None:
    delete_session(conn, parsed.session_id)
    conn.execute(
        """
        INSERT INTO sessions (
            session_id,
            file_path,
            modified_ns,
            size_bytes,
            started_at,
            cwd,
            source,
            model,
            title,
            summary,
            tool_names,
            message_text,
            indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            parsed.session_id,
            parsed.file_path,
            parsed.modified_ns,
            parsed.size_bytes,
            parsed.started_at,
            parsed.cwd,
            parsed.source,
            parsed.model,
            parsed.title,
            parsed.summary,
            json.dumps(parsed.tool_names),
            parsed.message_text,
            now_iso(),
        ),
    )

    for ordinal, message in enumerate(parsed.messages, start=1):
        conn.execute(
            """
            INSERT INTO messages (session_id, ordinal, timestamp, role, kind, text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.session_id,
                ordinal,
                message.get("timestamp", ""),
                message["role"],
                message["kind"],
                message["text"],
            ),
        )

    if fts_available(conn):
        conn.execute(
            """
            INSERT INTO session_fts (session_id, title, summary, cwd, tool_names, message_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.session_id,
                parsed.title,
                parsed.summary,
                parsed.cwd,
                " ".join(parsed.tool_names),
                parsed.message_text,
            ),
        )


def rebuild_index(force: bool = False) -> dict[str, int]:
    with connect_db() as conn:
        files = iter_session_files()
        current_paths = {str(path) for path in files}
        existing_rows = conn.execute(
            "SELECT session_id, file_path, modified_ns, size_bytes FROM sessions"
        ).fetchall()
        existing_by_path = {row["file_path"]: row for row in existing_rows}

        removed = 0
        for file_path, row in existing_by_path.items():
            if file_path in current_paths:
                continue
            delete_session(conn, row["session_id"])
            removed += 1

        updated = 0
        skipped = 0
        for path in files:
            file_path = str(path)
            stat = path.stat()
            existing = existing_by_path.get(file_path)
            if (
                not force
                and existing is not None
                and existing["modified_ns"] == stat.st_mtime_ns
                and existing["size_bytes"] == stat.st_size
            ):
                skipped += 1
                continue

            parsed = parse_session_file(path)
            if parsed is None:
                continue
            upsert_session(conn, parsed)
            updated += 1

        conn.commit()
        total = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
        return {
            "updated": updated,
            "removed": removed,
            "skipped": skipped,
            "total": total,
        }


def safe_fts_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_./:-]+", query)
    if not terms:
        return ""
    return " ".join(f'"{term}"' for term in terms[:12])


def iso_cutoff(days: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.replace(microsecond=0).isoformat()


def search_sessions(
    query: str,
    limit: int = 10,
    cwd_contains: str | None = None,
    days: int | None = None,
) -> list[dict[str, Any]]:
    rebuild_index(force=False)
    limit = max(1, min(int(limit), 25))
    params: list[Any] = []

    with connect_db() as conn:
        where_clauses: list[str] = []
        if cwd_contains:
            where_clauses.append("LOWER(s.cwd) LIKE ?")
            params.append(f"%{cwd_contains.lower()}%")
        if days is not None:
            where_clauses.append("s.started_at >= ?")
            params.append(iso_cutoff(int(days)))

        where_sql = ""
        if where_clauses:
            where_sql = " AND " + " AND ".join(where_clauses)

        fts_query = safe_fts_query(query)
        rows: list[sqlite3.Row]
        if fts_available(conn) and fts_query:
            rows = conn.execute(
                f"""
                SELECT
                    s.session_id,
                    s.started_at,
                    s.cwd,
                    s.title,
                    s.summary,
                    s.tool_names,
                    bm25(session_fts) AS rank
                FROM session_fts
                JOIN sessions s ON s.session_id = session_fts.session_id
                WHERE session_fts MATCH ? {where_sql}
                ORDER BY rank, s.started_at DESC
                LIMIT ?
                """,
                [fts_query, *params, limit],
            ).fetchall()
        else:
            like_term = f"%{query.lower()}%"
            rows = conn.execute(
                f"""
                SELECT
                    s.session_id,
                    s.started_at,
                    s.cwd,
                    s.title,
                    s.summary,
                    s.tool_names,
                    0.0 AS rank
                FROM sessions s
                WHERE (
                    LOWER(s.title) LIKE ?
                    OR LOWER(s.summary) LIKE ?
                    OR LOWER(s.message_text) LIKE ?
                ) {where_sql}
                ORDER BY s.started_at DESC
                LIMIT ?
                """,
                [like_term, like_term, like_term, *params, limit],
            ).fetchall()

    return [dict(row) for row in rows]


def recent_sessions(limit: int = 10, cwd_contains: str | None = None) -> list[dict[str, Any]]:
    rebuild_index(force=False)
    limit = max(1, min(int(limit), 25))
    params: list[Any] = []
    sql = """
        SELECT session_id, started_at, cwd, title, summary, tool_names
        FROM sessions
    """
    if cwd_contains:
        sql += " WHERE LOWER(cwd) LIKE ?"
        params.append(f"%{cwd_contains.lower()}%")
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    with connect_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_session(session_id: str, max_messages: int = 24) -> dict[str, Any] | None:
    rebuild_index(force=False)
    max_messages = max(1, min(int(max_messages), 100))
    with connect_db() as conn:
        session_row = conn.execute(
            """
            SELECT session_id, started_at, cwd, source, model, title, summary, tool_names
            FROM sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if session_row is None:
            return None

        message_rows = conn.execute(
            """
            SELECT ordinal, timestamp, role, kind, text
            FROM messages
            WHERE session_id = ?
            ORDER BY ordinal ASC
            LIMIT ?
            """,
            (session_id, max_messages),
        ).fetchall()
        total_messages = conn.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()["count"]

    payload = dict(session_row)
    payload["messages"] = [dict(row) for row in message_rows]
    payload["total_messages"] = total_messages
    return payload
