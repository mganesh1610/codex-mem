from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


CODEX_HOME = Path.home() / ".codex"
SESSION_ROOT = CODEX_HOME / "sessions"
STATE_DIR = CODEX_HOME / "memories" / "codex-mem"
DB_PATH = STATE_DIR / "memory.sqlite3"
DEFAULT_GROUPS_PATH = STATE_DIR / "project_groups.json"
DEFAULT_CHROMA_PATH = STATE_DIR / "chroma"

MAX_MESSAGE_TEXT = 8000
MAX_AGGREGATE_TEXT = 200000
MAX_SUMMARY_TEXT = 1200
MAX_CHROMA_DOCUMENT_TEXT = 60000
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
    project_groups: list[str]
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


def get_runtime_settings() -> dict[str, Any]:
    groups_path = Path(
        os.environ.get("CODEX_MEM_PROJECT_GROUPS_PATH", str(DEFAULT_GROUPS_PATH))
    ).expanduser()
    chroma_path = Path(
        os.environ.get("CODEX_MEM_CHROMA_PATH", str(DEFAULT_CHROMA_PATH))
    ).expanduser()
    return {
        "enable_chroma": os.environ.get("CODEX_MEM_ENABLE_CHROMA", "").lower() in {"1", "true", "yes", "on"},
        "chroma_collection": os.environ.get("CODEX_MEM_CHROMA_COLLECTION", "codex_mem_sessions"),
        "chroma_host": os.environ.get("CODEX_MEM_CHROMA_HOST", "").strip(),
        "chroma_port": int(os.environ.get("CODEX_MEM_CHROMA_PORT", "8000")),
        "chroma_path": chroma_path,
        "groups_path": groups_path,
    }


@lru_cache(maxsize=1)
def load_project_groups() -> list[dict[str, Any]]:
    settings = get_runtime_settings()
    path = settings["groups_path"]
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    raw_groups = payload.get("groups", [])
    groups: list[dict[str, Any]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, dict):
            continue
        name = str(raw_group.get("name") or "").strip()
        patterns = raw_group.get("patterns", [])
        aliases = raw_group.get("aliases", [])
        if not name or not isinstance(patterns, list):
            continue
        clean_patterns = [str(item).strip().lower() for item in patterns if str(item).strip()]
        clean_aliases = [str(item).strip().lower() for item in aliases if str(item).strip()]
        if not clean_patterns:
            continue
        groups.append(
            {
                "name": name,
                "patterns": clean_patterns,
                "aliases": clean_aliases,
                "description": str(raw_group.get("description") or "").strip(),
            }
        )
    return groups


def clear_group_cache() -> None:
    load_project_groups.cache_clear()


def list_project_groups() -> list[dict[str, Any]]:
    clear_group_cache()
    return load_project_groups()


def group_names_for_cwd(cwd: str) -> list[str]:
    normalized = cwd.lower()
    matches: list[str] = []
    for group in load_project_groups():
        for pattern in group["patterns"]:
            if pattern in normalized:
                matches.append(group["name"])
                break
    return unique_preserve_order(matches)


def resolve_group_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = name.strip().lower()
    if not normalized:
        return None
    for group in load_project_groups():
        if group["name"].lower() == normalized:
            return group["name"]
        if normalized in group["aliases"]:
            return group["name"]
    return name.strip()


def connect_db() -> sqlite3.Connection:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
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
            project_groups TEXT NOT NULL DEFAULT '[]',
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
    ensure_session_schema(conn)
    ensure_fts_schema(conn)


def ensure_session_schema(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    if "project_groups" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN project_groups TEXT NOT NULL DEFAULT '[]'")


def ensure_fts_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'session_fts'"
    ).fetchone()
    create_sql = """
        CREATE VIRTUAL TABLE session_fts USING fts5(
            session_id UNINDEXED,
            title,
            summary,
            cwd,
            tool_names,
            project_groups,
            message_text
        );
    """
    if row is None:
        conn.execute(create_sql)
        return
    sql = str(row["sql"] or "")
    if "project_groups" in sql:
        return
    conn.execute("DROP TABLE IF EXISTS session_fts")
    conn.execute(create_sql)


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
    project_groups = group_names_for_cwd(cwd)

    summary_parts: list[str] = []
    if meaningful_user_messages:
        summary_parts.append(f"Request: {trim_text(meaningful_user_messages[0], 350)}")
    if project_groups:
        summary_parts.append(f"Groups: {', '.join(project_groups)}")
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
        project_groups=project_groups,
        message_text=message_text,
        messages=messages,
    )


def document_for_chroma(parsed: ParsedSession) -> str:
    parts = [
        parsed.title,
        parsed.summary,
        f"cwd: {parsed.cwd}" if parsed.cwd else "",
        f"groups: {', '.join(parsed.project_groups)}" if parsed.project_groups else "",
        parsed.message_text,
    ]
    return trim_text("\n".join(part for part in parts if part), MAX_CHROMA_DOCUMENT_TEXT)


def chroma_enabled() -> bool:
    return bool(get_runtime_settings()["enable_chroma"])


def get_chroma_components() -> tuple[Any | None, Any | None, str | None]:
    if not chroma_enabled():
        return None, None, "disabled"
    try:
        import chromadb  # type: ignore
    except ImportError:
        return None, None, "chromadb package is not installed"

    settings = get_runtime_settings()
    try:
        if settings["chroma_host"]:
            client = chromadb.HttpClient(
                host=settings["chroma_host"],
                port=settings["chroma_port"],
            )
        else:
            settings["chroma_path"].mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(settings["chroma_path"]))
        collection = client.get_or_create_collection(name=settings["chroma_collection"])
        return client, collection, None
    except Exception as exc:  # pragma: no cover
        return None, None, str(exc)


def chroma_status() -> dict[str, Any]:
    settings = get_runtime_settings()
    _, collection, error = get_chroma_components()
    return {
        "enabled": settings["enable_chroma"],
        "available": collection is not None,
        "mode": "http" if settings["chroma_host"] else "persistent",
        "path": str(settings["chroma_path"]),
        "host": settings["chroma_host"] or None,
        "port": settings["chroma_port"] if settings["chroma_host"] else None,
        "collection": settings["chroma_collection"],
        "error": error,
    }


def chroma_metadata_for_session(parsed: ParsedSession) -> dict[str, Any]:
    return {
        "session_id": parsed.session_id,
        "started_at": parsed.started_at,
        "cwd": parsed.cwd,
        "title": parsed.title,
        "summary": parsed.summary,
        "project_groups": ",".join(parsed.project_groups),
        "source": parsed.source,
        "model": parsed.model,
    }


def sync_session_to_chroma(parsed: ParsedSession) -> None:
    _, collection, error = get_chroma_components()
    if collection is None:
        if chroma_enabled() and error:
            return
        return
    collection.upsert(
        ids=[parsed.session_id],
        documents=[document_for_chroma(parsed)],
        metadatas=[chroma_metadata_for_session(parsed)],
    )


def sync_sessions_to_chroma(parsed_sessions: list[ParsedSession]) -> None:
    if not parsed_sessions:
        return
    _, collection, error = get_chroma_components()
    if collection is None:
        if chroma_enabled() and error:
            return
        return
    try:
        collection.upsert(
            ids=[parsed.session_id for parsed in parsed_sessions],
            documents=[document_for_chroma(parsed) for parsed in parsed_sessions],
            metadatas=[chroma_metadata_for_session(parsed) for parsed in parsed_sessions],
        )
    except Exception:
        return


def delete_session_from_chroma(session_id: str) -> None:
    _, collection, _ = get_chroma_components()
    if collection is None:
        return
    try:
        collection.delete(ids=[session_id])
    except Exception:
        return


def delete_sessions_from_chroma(session_ids: list[str]) -> None:
    filtered_ids = [session_id for session_id in session_ids if session_id]
    if not filtered_ids:
        return
    _, collection, _ = get_chroma_components()
    if collection is None:
        return
    try:
        collection.delete(ids=filtered_ids)
    except Exception:
        return


def row_to_groups(row: sqlite3.Row | dict[str, Any]) -> list[str]:
    raw_value = row.get("project_groups") if isinstance(row, dict) else row["project_groups"]
    cwd_value = str(row.get("cwd") if isinstance(row, dict) else row["cwd"] or "")
    dynamic_groups = group_names_for_cwd(cwd_value)
    try:
        stored_groups = list(json.loads(raw_value or "[]"))
    except (TypeError, json.JSONDecodeError):
        stored_groups = []
    return unique_preserve_order(stored_groups + dynamic_groups)


def row_matches_filters(
    row: sqlite3.Row | dict[str, Any],
    cwd_contains: str | None = None,
    days: int | None = None,
    project_group: str | None = None,
) -> bool:
    if cwd_contains:
        cwd_value = str(row.get("cwd") if isinstance(row, dict) else row["cwd"] or "")
        if cwd_contains.lower() not in cwd_value.lower():
            return False
    if days is not None:
        started_at = str(row.get("started_at") if isinstance(row, dict) else row["started_at"] or "")
        if started_at and started_at < iso_cutoff(int(days)):
            return False
    if project_group:
        resolved_group = resolve_group_name(project_group)
        if resolved_group not in row_to_groups(row):
            return False
    return True


def delete_session(conn: sqlite3.Connection, session_id: str, sync_chroma: bool = True) -> None:
    if not session_id:
        return
    if fts_available(conn):
        conn.execute("DELETE FROM session_fts WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    if sync_chroma:
        delete_session_from_chroma(session_id)


def upsert_session(conn: sqlite3.Connection, parsed: ParsedSession, sync_chroma: bool = True) -> None:
    delete_session(conn, parsed.session_id, sync_chroma=False)
    project_groups_json = json.dumps(parsed.project_groups)
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
            project_groups,
            message_text,
            indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            project_groups_json,
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
            INSERT INTO session_fts (session_id, title, summary, cwd, tool_names, project_groups, message_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.session_id,
                parsed.title,
                parsed.summary,
                parsed.cwd,
                " ".join(parsed.tool_names),
                " ".join(parsed.project_groups),
                parsed.message_text,
            ),
        )

    if sync_chroma:
        sync_session_to_chroma(parsed)


def rebuild_index(force: bool = False) -> dict[str, int]:
    clear_group_cache()
    removed_session_ids: list[str] = []
    parsed_updates: list[ParsedSession] = []
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
            delete_session(conn, row["session_id"], sync_chroma=False)
            removed_session_ids.append(row["session_id"])
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
            upsert_session(conn, parsed, sync_chroma=False)
            parsed_updates.append(parsed)
            updated += 1

        conn.commit()
        total = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]

    delete_sessions_from_chroma(removed_session_ids)
    sync_sessions_to_chroma(parsed_updates)
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


def finalize_rows(
    rows: list[sqlite3.Row],
    limit: int,
    cwd_contains: str | None = None,
    days: int | None = None,
    project_group: str | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if not row_matches_filters(row, cwd_contains=cwd_contains, days=days, project_group=project_group):
            continue
        payload = dict(row)
        payload["project_groups"] = row_to_groups(row)
        filtered.append(payload)
        if len(filtered) >= limit:
            break
    return filtered


def search_sessions(
    query: str,
    limit: int = 10,
    cwd_contains: str | None = None,
    days: int | None = None,
    project_group: str | None = None,
) -> list[dict[str, Any]]:
    rebuild_index(force=False)
    limit = max(1, min(int(limit), 25))
    params: list[Any] = []
    sql_limit = max(limit * 8, 50)

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
                    s.project_groups,
                    bm25(session_fts) AS rank
                FROM session_fts
                JOIN sessions s ON s.session_id = session_fts.session_id
                WHERE session_fts MATCH ? {where_sql}
                ORDER BY rank, s.started_at DESC
                LIMIT ?
                """,
                [fts_query, *params, sql_limit],
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
                    s.project_groups,
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
                [like_term, like_term, like_term, *params, sql_limit],
            ).fetchall()

    return finalize_rows(rows, limit, cwd_contains=cwd_contains, days=days, project_group=project_group)


def semantic_search_sessions(
    query: str,
    limit: int = 10,
    cwd_contains: str | None = None,
    days: int | None = None,
    project_group: str | None = None,
) -> list[dict[str, Any]]:
    rebuild_index(force=False)
    limit = max(1, min(int(limit), 25))
    _, collection, _ = get_chroma_components()
    if collection is None:
        return []
    try:
        result = collection.query(
            query_texts=[query],
            n_results=max(limit * 8, 20),
            include=["metadatas", "distances"],
        )
    except Exception:
        return []

    metadatas = result.get("metadatas", [[]])[0] if result.get("metadatas") else []
    distances = result.get("distances", [[]])[0] if result.get("distances") else []
    rows: list[dict[str, Any]] = []
    for metadata, distance in zip(metadatas, distances):
        if not isinstance(metadata, dict):
            continue
        row = {
            "session_id": metadata.get("session_id", ""),
            "started_at": metadata.get("started_at", ""),
            "cwd": metadata.get("cwd", ""),
            "title": metadata.get("title", ""),
            "summary": metadata.get("summary", ""),
            "tool_names": json.dumps([]),
            "project_groups": json.dumps(
                [
                    item.strip()
                    for item in str(metadata.get("project_groups", "")).split(",")
                    if item.strip()
                ]
            ),
            "rank": float(distance if distance is not None else 9999.0),
            "semantic_score": float(1.0 / (1.0 + float(distance if distance is not None else 9999.0))),
        }
        if row_matches_filters(row, cwd_contains=cwd_contains, days=days, project_group=project_group):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def hybrid_search_sessions(
    query: str,
    limit: int = 10,
    cwd_contains: str | None = None,
    days: int | None = None,
    project_group: str | None = None,
) -> list[dict[str, Any]]:
    keyword_rows = search_sessions(
        query=query,
        limit=max(limit * 3, 20),
        cwd_contains=cwd_contains,
        days=days,
        project_group=project_group,
    )
    semantic_rows = semantic_search_sessions(
        query=query,
        limit=max(limit * 3, 20),
        cwd_contains=cwd_contains,
        days=days,
        project_group=project_group,
    )

    merged: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(keyword_rows, start=1):
        payload = dict(row)
        payload["project_groups"] = row.get("project_groups", [])
        payload["search_sources"] = ["keyword"]
        payload["hybrid_score"] = 1.0 / index
        merged[payload["session_id"]] = payload

    for index, row in enumerate(semantic_rows, start=1):
        payload = dict(row)
        payload["project_groups"] = row.get("project_groups", [])
        session_id = payload["session_id"]
        semantic_score = float(payload.get("semantic_score", 1.0 / index))
        if session_id in merged:
            existing = merged[session_id]
            existing["search_sources"] = unique_preserve_order(existing["search_sources"] + ["semantic"])
            existing["hybrid_score"] = float(existing.get("hybrid_score", 0.0)) + semantic_score
        else:
            payload["search_sources"] = ["semantic"]
            payload["hybrid_score"] = semantic_score
            merged[session_id] = payload

    ranked = sorted(
        merged.values(),
        key=lambda item: (-float(item.get("hybrid_score", 0.0)), str(item.get("started_at") or "")),
    )
    return ranked[:limit]


def recent_sessions(
    limit: int = 10,
    cwd_contains: str | None = None,
    project_group: str | None = None,
) -> list[dict[str, Any]]:
    rebuild_index(force=False)
    limit = max(1, min(int(limit), 25))
    params: list[Any] = []
    sql = """
        SELECT session_id, started_at, cwd, title, summary, tool_names, project_groups
        FROM sessions
    """
    if cwd_contains:
        sql += " WHERE LOWER(cwd) LIKE ?"
        params.append(f"%{cwd_contains.lower()}%")
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(max(limit * 8, 50))
    with connect_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return finalize_rows(rows, limit, cwd_contains=cwd_contains, project_group=project_group)


def get_session(session_id: str, max_messages: int = 24) -> dict[str, Any] | None:
    rebuild_index(force=False)
    max_messages = max(1, min(int(max_messages), 100))
    with connect_db() as conn:
        session_row = conn.execute(
            """
            SELECT session_id, started_at, cwd, source, model, title, summary, tool_names, project_groups
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
    payload["project_groups"] = row_to_groups(session_row)
    payload["messages"] = [dict(row) for row in message_rows]
    payload["total_messages"] = total_messages
    return payload


def get_startup_context(
    cwd: str | None = None,
    query: str | None = None,
    limit: int = 5,
    project_group: str | None = None,
) -> dict[str, Any]:
    effective_group = resolve_group_name(project_group)
    inferred_groups = group_names_for_cwd(cwd or "")
    effective_group = effective_group or (inferred_groups[0] if inferred_groups else None)
    if query:
        sessions = hybrid_search_sessions(
            query=query,
            limit=limit,
            cwd_contains=cwd,
            project_group=effective_group,
        )
    else:
        sessions = recent_sessions(
            limit=limit,
            cwd_contains=cwd,
            project_group=effective_group,
        )
    return {
        "cwd": cwd or "",
        "project_group": effective_group,
        "inferred_groups": inferred_groups,
        "sessions": sessions,
    }


def memory_status() -> dict[str, Any]:
    rebuild_index(force=False)
    with connect_db() as conn:
        total_sessions = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
        total_messages = conn.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"]
        latest = conn.execute(
            "SELECT started_at FROM sessions ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    return {
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "latest_session_started_at": latest["started_at"] if latest else None,
        "session_root": str(SESSION_ROOT),
        "database_path": str(DB_PATH),
        "project_groups_path": str(get_runtime_settings()["groups_path"]),
        "project_group_count": len(list_project_groups()),
        "chroma": chroma_status(),
    }


def write_project_groups_example(force: bool = False) -> Path:
    settings = get_runtime_settings()
    path = settings["groups_path"]
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    example = {
        "groups": [
            {
                "name": "biodesign-samples",
                "description": "Merge serum, plasma, and saliva related workspaces into one memory space.",
                "patterns": [
                    "OneDrive - Arizona State University\\Biodesign\\Serum, Plasma and Saliva samples\\raw",
                    "OneDrive - Arizona State University\\Biodesign\\Serum, Plasma and Saliva samples\\processed"
                ],
                "aliases": ["biodesign", "samples"]
            }
        ]
    }
    path.write_text(json.dumps(example, indent=2) + "\n", encoding="utf-8")
    clear_group_cache()
    return path
