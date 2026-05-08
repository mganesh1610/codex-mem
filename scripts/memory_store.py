from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote


CODEX_HOME = Path.home() / ".codex"
SESSION_ROOT = CODEX_HOME / "sessions"
STATE_DIR = CODEX_HOME / "memories" / "codex-mem"
DB_PATH = STATE_DIR / "memory.sqlite3"
DEFAULT_GROUPS_PATH = STATE_DIR / "project_groups.json"
DEFAULT_CHROMA_PATH = STATE_DIR / "chroma"
DEFAULT_OBSIDIAN_VAULT_PATH = STATE_DIR / "obsidian-vault"
DEFAULT_OBSIDIAN_FOLDER = "Codex Mem"

MAX_MESSAGE_TEXT = 8000
MAX_AGGREGATE_TEXT = 200000
MAX_SUMMARY_TEXT = 1200
MAX_DECISION_TEXT = 700
MAX_CHROMA_DOCUMENT_TEXT = 60000
TITLE_FALLBACK = "Untitled session"
DEFAULT_MATCH_RADIUS = 220

WHITESPACE_RE = re.compile(r"\s+")
INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
ENV_BLOCK_RE = re.compile(r"<environment_context>.*?</environment_context>", re.DOTALL)
XML_TAG_RE = re.compile(r"</?[^>]+>")
FILE_TOKEN_RE = re.compile(
    r"(?P<path>"
    r"(?:[A-Za-z]:\\[^<>\"'\n\r]+)"
    r"|(?:/(?:[^/\s]+/)*[^/\s]+\.[A-Za-z0-9]{1,8})"
    r"|(?:(?:[A-Za-z0-9._ -]+[\\/])+[A-Za-z0-9._ -]+\.[A-Za-z0-9]{1,8})"
    r"|(?:[A-Za-z0-9._ -]+\.(?:py|ts|tsx|js|jsx|json|toml|yml|yaml|md|sql|csv|txt|ps1|sh|ipynb|pdf|xlsx|pptx|docx|html|css))"
    r")(?::\d+)?"
)
ERROR_TEXT_RE = re.compile(
    r"\b(error|exception|traceback|failed|failure|not found|denied|invalid|timed out|refused|crash|fatal)\b",
    re.IGNORECASE,
)
SEARCH_TERM_RE = re.compile(r"[A-Za-z0-9_./:-]+")
COMMON_FILE_EXTENSIONS = {
    "py", "ts", "tsx", "js", "jsx", "json", "toml", "yml", "yaml", "md", "sql",
    "csv", "txt", "ps1", "sh", "ipynb", "pdf", "xlsx", "pptx", "docx", "html", "css"
}
DOMAIN_LIKE_EXTENSIONS = {"com", "org", "net", "io", "ai", "edu", "gov"}


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
    decision_summary: str
    tool_names: list[str]
    files_touched: list[str]
    commands_seen: list[str]
    error_signatures: list[str]
    project_groups: list[str]
    obsidian_note_path: str
    obsidian_uri: str
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


def normalize_message_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw_line in normalized.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def trim_message_text(text: str, limit: int) -> str:
    value = normalize_message_text(text)
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


def normalize_session_title(text: str) -> str:
    value = clean_user_text(text)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("`", "")
    value = re.sub(r"^[#*\-]+\s*", "", value)
    value = re.sub(r"^files mentioned by the user:\s*", "", value, flags=re.IGNORECASE)
    value = collapse_whitespace(value)
    if value.lower().startswith("agents.md instructions for "):
        return ""
    return value


def unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def safe_slug(text: str, fallback: str = "note") -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", text).strip().replace(" ", "-")
    value = re.sub(r"-{2,}", "-", value).strip("-.")
    return value or fallback


def safe_note_name(started_at: str, title: str, cwd: str, session_id: str) -> str:
    timestamp = ""
    if started_at:
        normalized = started_at.replace("Z", "+00:00")
        try:
            timestamp = datetime.fromisoformat(normalized).strftime("%Y-%m-%d %H-%M-%S")
        except ValueError:
            timestamp = started_at.split("T", 1)[0]

    project_name = collapse_whitespace(Path(cwd).name) if cwd else ""
    title_text = normalize_session_title(title) if title else ""
    if not title_text:
        title_text = TITLE_FALLBACK
    parts = [timestamp]
    if project_name and project_name.lower() not in title_text.lower():
        parts.append(project_name)
    parts.append(title_text)

    note_name = " - ".join(part for part in parts if part)
    note_name = INVALID_FILENAME_RE.sub(" ", note_name)
    note_name = collapse_whitespace(note_name).strip(" .")
    if len(note_name) > 120:
        note_name = trim_text(note_name, 120).rstrip(". ")
    return note_name or safe_slug(session_id[:8] or session_id or "session", "session")


def get_runtime_settings() -> dict[str, Any]:
    groups_path = Path(
        os.environ.get("CODEX_MEM_PROJECT_GROUPS_PATH", str(DEFAULT_GROUPS_PATH))
    ).expanduser()
    extra_session_roots = [
        Path(item).expanduser()
        for item in re.split(r"[;\n]", os.environ.get("CODEX_MEM_EXTRA_SESSION_ROOTS", ""))
        if item.strip()
    ]
    chroma_path = Path(
        os.environ.get("CODEX_MEM_CHROMA_PATH", str(DEFAULT_CHROMA_PATH))
    ).expanduser()
    obsidian_vault_path = Path(
        os.environ.get("CODEX_MEM_OBSIDIAN_VAULT_PATH", str(DEFAULT_OBSIDIAN_VAULT_PATH))
    ).expanduser()
    return {
        "enable_chroma": os.environ.get("CODEX_MEM_ENABLE_CHROMA", "").lower() in {"1", "true", "yes", "on"},
        "enable_obsidian": os.environ.get("CODEX_MEM_ENABLE_OBSIDIAN", "1").lower() not in {"0", "false", "no", "off"},
        "chroma_collection": os.environ.get("CODEX_MEM_CHROMA_COLLECTION", "codex_mem_sessions"),
        "chroma_host": os.environ.get("CODEX_MEM_CHROMA_HOST", "").strip(),
        "chroma_port": int(os.environ.get("CODEX_MEM_CHROMA_PORT", "8000")),
        "chroma_path": chroma_path,
        "groups_path": groups_path,
        "session_roots": unique_paths([SESSION_ROOT, *extra_session_roots]),
        "obsidian_vault_path": obsidian_vault_path,
        "obsidian_folder": os.environ.get("CODEX_MEM_OBSIDIAN_FOLDER", DEFAULT_OBSIDIAN_FOLDER).strip() or DEFAULT_OBSIDIAN_FOLDER,
    }


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in paths:
        resolved = path.expanduser()
        key = str(resolved).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(resolved)
    return ordered


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


def obsidian_root_dir() -> Path:
    settings = get_runtime_settings()
    return settings["obsidian_vault_path"] / settings["obsidian_folder"]


def obsidian_enabled() -> bool:
    return bool(get_runtime_settings()["enable_obsidian"])


def note_location(started_at: str, session_id: str, title: str, cwd: str) -> tuple[str, str]:
    if not obsidian_enabled():
        return "", ""
    year = "unknown"
    month = "unknown"
    if started_at:
        parts = started_at.split("-")
        if len(parts) >= 2:
            year = parts[0]
            month = parts[1]
    note_name = safe_note_name(started_at, title, cwd, session_id)
    note_path = obsidian_root_dir() / "Sessions" / year / month / f"{note_name}.md"
    return str(note_path), obsidian_uri_for_path(note_path)


def obsidian_uri_for_path(path: Path) -> str:
    return f"obsidian://open?path={quote(str(path))}"


def strip_line_suffix(path: str) -> str:
    if re.search(r":[0-9]+$", path):
        return re.sub(r":[0-9]+$", "", path)
    return path


def normalize_detected_path(value: str) -> str:
    cleaned = value.strip().strip("()[]<>\"'")
    cleaned = strip_line_suffix(cleaned)
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.replace("\\\\", "\\")
    cleaned = re.sub(r"^\d{1,2}\s+(?:AM|PM)\s+\d+\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\d{1,2}\s+(?:AM|PM)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.rstrip(".,:;")
    return cleaned


def extract_file_tokens(text: str) -> list[str]:
    matches: list[str] = []
    for match in FILE_TOKEN_RE.finditer(text):
        candidate = normalize_detected_path(match.group("path"))
        if not candidate:
            continue
        if candidate.lower().startswith((
            "get-childitem ",
            "get-content ",
            "python ",
            "python3 ",
            "git ",
            "$env:",
            "select-object ",
            "format-table ",
            "where-object ",
            "the generated ",
        )):
            continue
        if " and " in candidate.lower() and "\\" not in candidate and "/" not in candidate:
            continue
        if candidate.lower().startswith(("http://", "https://", "obsidian://")):
            continue
        if candidate.lower().startswith(("/github.", "/huggingface.", "/openai.", "/docs.")):
            continue
        suffix = candidate.rsplit(".", 1)[-1].lower() if "." in candidate else ""
        if suffix in DOMAIN_LIKE_EXTENSIONS:
            continue
        if "\\" not in candidate and "/" not in candidate and suffix not in COMMON_FILE_EXTENSIONS:
            continue
        if len(candidate) < 4:
            continue
        matches.append(candidate)
    ordered = unique_preserve_order(matches)
    filtered: list[str] = []
    for candidate in ordered:
        lowered = candidate.lower()
        if any(
            lowered != other.lower() and lowered in other.lower() and len(other) > len(candidate) + 8
            for other in ordered
        ):
            continue
        filtered.append(candidate)
    return filtered


def extract_error_signatures(texts: list[str]) -> list[str]:
    matches: list[str] = []
    for text in texts:
        for line in normalize_message_text(text).splitlines():
            if ERROR_TEXT_RE.search(line):
                if "\"timeout\":" in line.lower():
                    continue
                matches.append(trim_text(line, 240))
    return unique_preserve_order(matches)[:24]


def extract_command_from_arguments(tool_name: str, arguments: str) -> str | None:
    lowered = tool_name.lower()
    if "shell_command" not in lowered:
        return None
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return None
    command = payload.get("command")
    if not isinstance(command, str):
        return None
    return trim_text(command, 300)


def choose_decision_text(assistant_messages: list[str]) -> str:
    if not assistant_messages:
        return ""

    def score(text: str) -> int:
        lowered = text.lower()
        result = len(text)
        if any(token in lowered for token in ["updated", "added", "fixed", "implemented", "changed", "documented", "created", "now ", "recommend", "use ", "keep "]):
            result += 180
        if any(token in lowered for token in ["i'm ", "i am ", "i’ll ", "i'll ", "checking", "reading", "moving to", "rerunning", "installing", "editing", "about to"]):
            result -= 140
        return result

    candidate = max(assistant_messages[-5:], key=score)
    return trim_text(candidate, MAX_DECISION_TEXT)


def tokenize_search_text(text: str | None) -> list[str]:
    if not text:
        return []
    return [term.lower() for term in SEARCH_TERM_RE.findall(text)[:12]]


def make_snippet(text: str, terms: list[str], radius: int = DEFAULT_MATCH_RADIUS) -> str:
    normalized = normalize_message_text(text)
    if not normalized:
        return ""
    lower_text = normalized.lower()
    best_index = 0
    for term in terms:
        best_index = lower_text.find(term.lower())
        if best_index >= 0:
            break
    if best_index < 0:
        best_index = 0
    start = max(0, best_index - radius)
    end = min(len(normalized), best_index + radius)
    snippet = normalized[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(normalized):
        snippet = snippet + "..."
    return snippet


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
            decision_summary TEXT NOT NULL DEFAULT '',
            tool_names TEXT NOT NULL,
            files_touched TEXT NOT NULL DEFAULT '[]',
            commands_seen TEXT NOT NULL DEFAULT '[]',
            error_signatures TEXT NOT NULL DEFAULT '[]',
            project_groups TEXT NOT NULL DEFAULT '[]',
            obsidian_note_path TEXT NOT NULL DEFAULT '',
            obsidian_uri TEXT NOT NULL DEFAULT '',
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
    ensure_message_fts_schema(conn)


def ensure_session_schema(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    if "decision_summary" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN decision_summary TEXT NOT NULL DEFAULT ''")
    if "files_touched" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN files_touched TEXT NOT NULL DEFAULT '[]'")
    if "commands_seen" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN commands_seen TEXT NOT NULL DEFAULT '[]'")
    if "error_signatures" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN error_signatures TEXT NOT NULL DEFAULT '[]'")
    if "project_groups" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN project_groups TEXT NOT NULL DEFAULT '[]'")
    if "obsidian_note_path" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN obsidian_note_path TEXT NOT NULL DEFAULT ''")
    if "obsidian_uri" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN obsidian_uri TEXT NOT NULL DEFAULT ''")


def ensure_fts_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'session_fts'"
    ).fetchone()
    create_sql = """
        CREATE VIRTUAL TABLE session_fts USING fts5(
            session_id UNINDEXED,
            title,
            summary,
            decision_summary,
            cwd,
            tool_names,
            files_touched,
            commands_seen,
            error_signatures,
            project_groups,
            message_text
        );
    """
    if row is None:
        conn.execute(create_sql)
        return
    sql = str(row["sql"] or "")
    required_tokens = [
        "decision_summary",
        "files_touched",
        "commands_seen",
        "error_signatures",
        "project_groups",
    ]
    if all(token in sql for token in required_tokens):
        return
    conn.execute("DROP TABLE IF EXISTS session_fts")
    conn.execute(create_sql)


def ensure_message_fts_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'message_fts'"
    ).fetchone()
    create_sql = """
        CREATE VIRTUAL TABLE message_fts USING fts5(
            message_id UNINDEXED,
            session_id UNINDEXED,
            role,
            kind,
            text
        );
    """
    if row is None:
        conn.execute(create_sql)
        return
    sql = str(row["sql"] or "")
    if "message_id" in sql and "session_id" in sql:
        return
    conn.execute("DROP TABLE IF EXISTS message_fts")
    conn.execute(create_sql)


def fts_available(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'session_fts'"
    ).fetchone()
    return row is not None


def iter_session_files() -> list[Path]:
    files: list[Path] = []
    for root in get_runtime_settings()["session_roots"]:
        if not root.exists():
            continue
        files.extend(root.rglob("*.jsonl"))
    return sorted(unique_paths(files), key=lambda path: str(path).lower())


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
    cleaned = trim_message_text(text, MAX_MESSAGE_TEXT)
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
    commands_seen: list[str] = []
    messages: list[dict[str, str]] = []
    extraction_texts: list[str] = []

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
                    extraction_texts.append(text)
                elif item_type == "reasoning":
                    summary = "\n".join(extract_content_texts(payload.get("summary")))
                    append_message(messages, "assistant", "reasoning", summary, timestamp)
                    extraction_texts.append(summary)
                elif item_type == "function_call":
                    name = str(payload.get("name") or "tool")
                    arguments = str(payload.get("arguments") or "")
                    tool_names.append(name)
                    command = extract_command_from_arguments(name, arguments)
                    if command:
                        commands_seen.append(command)
                    append_message(
                        messages,
                        "tool",
                        "tool_call",
                        f"{name}: {arguments}",
                        timestamp,
                    )
                    extraction_texts.append(f"{name}: {arguments}")
                elif item_type == "function_call_output":
                    output = str(payload.get("output") or "")
                    append_message(messages, "tool", "tool_output", output, timestamp)
                    extraction_texts.append(output)
                elif item_type == "custom_tool_call":
                    name = str(payload.get("name") or "custom_tool")
                    tool_names.append(name)
                elif item_type == "custom_tool_call_output":
                    output = str(payload.get("output") or "")
                    append_message(messages, "tool", "tool_output", output, timestamp)
                    extraction_texts.append(output)
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
                    extraction_texts.append(str(payload.get("text") or ""))

    if not started_at:
        started_at = datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat()

    meaningful_user_messages: list[str] = []
    for message in messages:
        if message["role"] != "user" or not message["text"]:
            continue
        title_candidate = normalize_session_title(message["text"])
        if title_candidate:
            meaningful_user_messages.append(title_candidate)
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
    commands_seen = unique_preserve_order(commands_seen)
    project_groups = group_names_for_cwd(cwd)
    files_touched = extract_file_tokens("\n".join([cwd, *extraction_texts]))
    error_source_texts = [
        message["text"]
        for message in messages
        if message["role"] in {"assistant", "tool"}
    ]
    error_signatures = extract_error_signatures(error_source_texts)
    decision_summary = choose_decision_text(assistant_messages)
    obsidian_note_path, obsidian_uri = note_location(started_at, session_id, title, cwd)

    summary_parts: list[str] = []
    if meaningful_user_messages:
        summary_parts.append(f"Request: {trim_text(meaningful_user_messages[0], 350)}")
    if decision_summary:
        summary_parts.append(f"Decision: {trim_text(decision_summary, 280)}")
    if project_groups:
        summary_parts.append(f"Groups: {', '.join(project_groups)}")
    if tool_names:
        summary_parts.append(f"Tools: {', '.join(tool_names[:8])}")
    if error_signatures:
        summary_parts.append(f"Errors: {', '.join(error_signatures[:2])}")
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
        decision_summary=decision_summary,
        tool_names=tool_names,
        files_touched=files_touched,
        commands_seen=commands_seen,
        error_signatures=error_signatures,
        project_groups=project_groups,
        obsidian_note_path=obsidian_note_path,
        obsidian_uri=obsidian_uri,
        message_text=message_text,
        messages=messages,
    )


def document_for_chroma(parsed: ParsedSession) -> str:
    parts = [
        parsed.title,
        parsed.summary,
        parsed.decision_summary,
        f"cwd: {parsed.cwd}" if parsed.cwd else "",
        f"groups: {', '.join(parsed.project_groups)}" if parsed.project_groups else "",
        f"files: {', '.join(parsed.files_touched[:12])}" if parsed.files_touched else "",
        f"commands: {', '.join(parsed.commands_seen[:8])}" if parsed.commands_seen else "",
        f"errors: {', '.join(parsed.error_signatures[:6])}" if parsed.error_signatures else "",
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
        "decision_summary": parsed.decision_summary,
        "tool_names": ",".join(parsed.tool_names),
        "project_groups": ",".join(parsed.project_groups),
        "files_touched": ",".join(parsed.files_touched),
        "commands_seen": ",".join(parsed.commands_seen),
        "error_signatures": ",".join(parsed.error_signatures),
        "source": parsed.source,
        "model": parsed.model,
        "obsidian_note_path": parsed.obsidian_note_path,
        "obsidian_uri": parsed.obsidian_uri,
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


def row_json_list(row: sqlite3.Row | dict[str, Any], key: str) -> list[str]:
    raw_value = row.get(key) if isinstance(row, dict) else row[key]
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if str(item).strip()]
    try:
        decoded = json.loads(raw_value or "[]")
    except (TypeError, json.JSONDecodeError):
        decoded = []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded if str(item).strip()]


def row_contains_list_value(row: sqlite3.Row | dict[str, Any], key: str, needle: str | None) -> bool:
    if not needle:
        return True
    lowered = needle.lower()
    return any(lowered in item.lower() for item in row_json_list(row, key))


def row_matches_filters(
    row: sqlite3.Row | dict[str, Any],
    cwd_contains: str | None = None,
    days: int | None = None,
    project_group: str | None = None,
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
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
    if not row_contains_list_value(row, "tool_names", tool_name):
        return False
    if not row_contains_list_value(row, "files_touched", file_contains):
        return False
    if not row_contains_list_value(row, "commands_seen", command_contains):
        return False
    if not row_contains_list_value(row, "error_signatures", error_contains):
        return False
    return True


def delete_session(conn: sqlite3.Connection, session_id: str, sync_chroma: bool = True) -> None:
    if not session_id:
        return
    if fts_available(conn):
        conn.execute("DELETE FROM session_fts WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM message_fts WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    if sync_chroma:
        delete_session_from_chroma(session_id)


def upsert_session(conn: sqlite3.Connection, parsed: ParsedSession, sync_chroma: bool = True) -> None:
    delete_session(conn, parsed.session_id, sync_chroma=False)
    project_groups_json = json.dumps(parsed.project_groups)
    files_touched_json = json.dumps(parsed.files_touched)
    commands_seen_json = json.dumps(parsed.commands_seen)
    error_signatures_json = json.dumps(parsed.error_signatures)
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
            decision_summary,
            tool_names,
            files_touched,
            commands_seen,
            error_signatures,
            project_groups,
            obsidian_note_path,
            obsidian_uri,
            message_text,
            indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            parsed.decision_summary,
            json.dumps(parsed.tool_names),
            files_touched_json,
            commands_seen_json,
            error_signatures_json,
            project_groups_json,
            parsed.obsidian_note_path,
            parsed.obsidian_uri,
            parsed.message_text,
            now_iso(),
        ),
    )

    for ordinal, message in enumerate(parsed.messages, start=1):
        cursor = conn.execute(
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
        conn.execute(
            """
            INSERT INTO message_fts (message_id, session_id, role, kind, text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(cursor.lastrowid),
                parsed.session_id,
                message["role"],
                message["kind"],
                message["text"],
            ),
        )

    if fts_available(conn):
        conn.execute(
            """
            INSERT INTO session_fts (
                session_id,
                title,
                summary,
                decision_summary,
                cwd,
                tool_names,
                files_touched,
                commands_seen,
                error_signatures,
                project_groups,
                message_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.session_id,
                parsed.title,
                parsed.summary,
                parsed.decision_summary,
                parsed.cwd,
                " ".join(parsed.tool_names),
                " ".join(parsed.files_touched),
                " ".join(parsed.commands_seen),
                " ".join(parsed.error_signatures),
                " ".join(parsed.project_groups),
                parsed.message_text,
            ),
        )

    if sync_chroma:
        sync_session_to_chroma(parsed)


def rebuild_index(force: bool = False) -> dict[str, int]:
    clear_group_cache()
    removed_session_ids: list[str] = []
    removed_note_paths: list[str] = []
    renamed_note_paths: list[str] = []
    expected_note_paths: list[str] = []
    parsed_updates: list[ParsedSession] = []
    with connect_db() as conn:
        files = iter_session_files()
        current_paths = {str(path) for path in files}
        existing_rows = conn.execute(
            "SELECT session_id, file_path, modified_ns, size_bytes, obsidian_note_path FROM sessions"
        ).fetchall()
        existing_by_path = {row["file_path"]: row for row in existing_rows}

        removed = 0
        for file_path, row in existing_by_path.items():
            if file_path in current_paths:
                continue
            delete_session(conn, row["session_id"], sync_chroma=False)
            removed_session_ids.append(row["session_id"])
            removed_note_paths.append(str(row["obsidian_note_path"] or ""))
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
            previous_note_path = str(existing["obsidian_note_path"] or "") if existing is not None else ""
            if previous_note_path and previous_note_path != parsed.obsidian_note_path:
                renamed_note_paths.append(previous_note_path)
            upsert_session(conn, parsed, sync_chroma=False)
            parsed_updates.append(parsed)
            updated += 1

        conn.commit()
        total = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
        expected_note_paths = [
            str(row["obsidian_note_path"] or "")
            for row in conn.execute("SELECT obsidian_note_path FROM sessions").fetchall()
        ]

    delete_sessions_from_chroma(removed_session_ids)
    for note_path in unique_preserve_order([*removed_note_paths, *renamed_note_paths]):
        delete_session_from_obsidian(note_path)
    sync_sessions_to_obsidian(parsed_updates)
    cleanup_stale_obsidian_session_notes(expected_note_paths)
    write_obsidian_index_notes()
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
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if not row_matches_filters(
            row,
            cwd_contains=cwd_contains,
            days=days,
            project_group=project_group,
            tool_name=tool_name,
            file_contains=file_contains,
            command_contains=command_contains,
            error_contains=error_contains,
        ):
            continue
        payload = dict(row)
        payload["project_groups"] = row_to_groups(row)
        payload["tool_names"] = row_json_list(row, "tool_names")
        payload["files_touched"] = row_json_list(row, "files_touched")
        payload["commands_seen"] = row_json_list(row, "commands_seen")
        payload["error_signatures"] = row_json_list(row, "error_signatures")
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
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
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
                    s.decision_summary,
                    s.tool_names,
                    s.files_touched,
                    s.commands_seen,
                    s.error_signatures,
                    s.project_groups,
                    s.obsidian_note_path,
                    s.obsidian_uri,
                    s.file_path,
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
                    s.decision_summary,
                    s.tool_names,
                    s.files_touched,
                    s.commands_seen,
                    s.error_signatures,
                    s.project_groups,
                    s.obsidian_note_path,
                    s.obsidian_uri,
                    s.file_path,
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

    return finalize_rows(
        rows,
        limit,
        cwd_contains=cwd_contains,
        days=days,
        project_group=project_group,
        tool_name=tool_name,
        file_contains=file_contains,
        command_contains=command_contains,
        error_contains=error_contains,
    )


def semantic_search_sessions(
    query: str,
    limit: int = 10,
    cwd_contains: str | None = None,
    days: int | None = None,
    project_group: str | None = None,
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
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
            "decision_summary": metadata.get("decision_summary", ""),
            "tool_names": json.dumps(
                [item.strip() for item in str(metadata.get("tool_names", "")).split(",") if item.strip()]
            ),
            "files_touched": json.dumps(
                [item.strip() for item in str(metadata.get("files_touched", "")).split(",") if item.strip()]
            ),
            "commands_seen": json.dumps(
                [item.strip() for item in str(metadata.get("commands_seen", "")).split(",") if item.strip()]
            ),
            "error_signatures": json.dumps(
                [item.strip() for item in str(metadata.get("error_signatures", "")).split(",") if item.strip()]
            ),
            "project_groups": json.dumps(
                [
                    item.strip()
                    for item in str(metadata.get("project_groups", "")).split(",")
                    if item.strip()
                ]
            ),
            "obsidian_note_path": metadata.get("obsidian_note_path", ""),
            "obsidian_uri": metadata.get("obsidian_uri", ""),
            "file_path": "",
            "rank": float(distance if distance is not None else 9999.0),
            "semantic_score": float(1.0 / (1.0 + float(distance if distance is not None else 9999.0))),
        }
        if row_matches_filters(
            row,
            cwd_contains=cwd_contains,
            days=days,
            project_group=project_group,
            tool_name=tool_name,
            file_contains=file_contains,
            command_contains=command_contains,
            error_contains=error_contains,
        ):
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
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
) -> list[dict[str, Any]]:
    keyword_rows = search_sessions(
        query=query,
        limit=max(limit * 3, 20),
        cwd_contains=cwd_contains,
        days=days,
        project_group=project_group,
        tool_name=tool_name,
        file_contains=file_contains,
        command_contains=command_contains,
        error_contains=error_contains,
    )
    semantic_rows = semantic_search_sessions(
        query=query,
        limit=max(limit * 3, 20),
        cwd_contains=cwd_contains,
        days=days,
        project_group=project_group,
        tool_name=tool_name,
        file_contains=file_contains,
        command_contains=command_contains,
        error_contains=error_contains,
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
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
) -> list[dict[str, Any]]:
    rebuild_index(force=False)
    limit = max(1, min(int(limit), 25))
    params: list[Any] = []
    sql = """
        SELECT
            session_id,
            started_at,
            cwd,
            title,
            summary,
            decision_summary,
            tool_names,
            files_touched,
            commands_seen,
            error_signatures,
            project_groups,
            obsidian_note_path,
            obsidian_uri,
            file_path
        FROM sessions
    """
    if cwd_contains:
        sql += " WHERE LOWER(cwd) LIKE ?"
        params.append(f"%{cwd_contains.lower()}%")
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(max(limit * 8, 50))
    with connect_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return finalize_rows(
        rows,
        limit,
        cwd_contains=cwd_contains,
        project_group=project_group,
        tool_name=tool_name,
        file_contains=file_contains,
        command_contains=command_contains,
        error_contains=error_contains,
    )


def get_session(session_id: str, max_messages: int = 24) -> dict[str, Any] | None:
    rebuild_index(force=False)
    max_messages = max(1, min(int(max_messages), 100))
    with connect_db() as conn:
        session_row = conn.execute(
            """
            SELECT
                session_id,
                started_at,
                cwd,
                source,
                model,
                title,
                summary,
                decision_summary,
                tool_names,
                files_touched,
                commands_seen,
                error_signatures,
                project_groups,
                obsidian_note_path,
                obsidian_uri,
                file_path
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
    payload["tool_names"] = row_json_list(session_row, "tool_names")
    payload["files_touched"] = row_json_list(session_row, "files_touched")
    payload["commands_seen"] = row_json_list(session_row, "commands_seen")
    payload["error_signatures"] = row_json_list(session_row, "error_signatures")
    payload["messages"] = [dict(row) for row in message_rows]
    payload["total_messages"] = total_messages
    return payload


def get_startup_context(
    cwd: str | None = None,
    query: str | None = None,
    limit: int = 5,
    project_group: str | None = None,
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
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
            tool_name=tool_name,
            file_contains=file_contains,
            command_contains=command_contains,
            error_contains=error_contains,
        )
    else:
        sessions = recent_sessions(
            limit=limit,
            cwd_contains=cwd,
            project_group=effective_group,
            tool_name=tool_name,
            file_contains=file_contains,
            command_contains=command_contains,
            error_contains=error_contains,
        )
    return {
        "cwd": cwd or "",
        "project_group": effective_group,
        "inferred_groups": inferred_groups,
        "sessions": sessions,
    }


def related_sessions(
    cwd: str | None = None,
    query: str | None = None,
    limit: int = 5,
    project_group: str | None = None,
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
) -> dict[str, Any]:
    return get_startup_context(
        cwd=cwd,
        query=query,
        limit=limit,
        project_group=project_group,
        tool_name=tool_name,
        file_contains=file_contains,
        command_contains=command_contains,
        error_contains=error_contains,
    )


def looks_like_error_text(text: str) -> bool:
    return bool(ERROR_TEXT_RE.search(text))


def message_matches_terms(
    text: str,
    query: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
    error_only: bool = False,
) -> bool:
    lowered = text.lower()
    if query:
        if query.lower() not in lowered:
            tokens = tokenize_search_text(query)
            if tokens and not any(token in lowered for token in tokens):
                return False
    if file_contains and file_contains.lower() not in lowered:
        return False
    if command_contains and command_contains.lower() not in lowered:
        return False
    if error_contains and error_contains.lower() not in lowered:
        return False
    if error_only and not looks_like_error_text(text):
        return False
    return True


def snippet_score(
    text: str,
    query: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
    role: str | None = None,
    kind: str | None = None,
) -> int:
    lowered = text.lower()
    score = 0
    if query:
        if query.lower() in lowered:
            score += 100
        score += sum(12 for token in tokenize_search_text(query) if token in lowered)
    if file_contains and file_contains.lower() in lowered:
        score += 60
    if command_contains and command_contains.lower() in lowered:
        score += 60
    if error_contains and error_contains.lower() in lowered:
        score += 60
    if kind == "tool_output":
        score += 20
    if role == "assistant":
        score += 10
    return score


def search_transcript_snippets(
    query: str | None = None,
    limit: int = 10,
    cwd_contains: str | None = None,
    days: int | None = None,
    project_group: str | None = None,
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
    error_only: bool = False,
) -> list[dict[str, Any]]:
    rebuild_index(force=False)
    limit = max(1, min(int(limit), 25))
    session_limit = max(limit * 12, 120)

    with connect_db() as conn:
        session_rows = conn.execute(
            """
            SELECT
                session_id,
                started_at,
                cwd,
                title,
                summary,
                decision_summary,
                tool_names,
                files_touched,
                commands_seen,
                error_signatures,
                project_groups,
                obsidian_note_path,
                obsidian_uri,
                file_path
            FROM sessions
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (session_limit,),
        ).fetchall()

        candidate_sessions = [
            dict(row)
            for row in session_rows
            if row_matches_filters(
                row,
                cwd_contains=cwd_contains,
                days=days,
                project_group=project_group,
                tool_name=tool_name,
                file_contains=file_contains,
                command_contains=command_contains,
                error_contains=error_contains,
            )
        ]

        results: list[dict[str, Any]] = []
        for session in candidate_sessions:
            message_rows = conn.execute(
                """
                SELECT ordinal, timestamp, role, kind, text
                FROM messages
                WHERE session_id = ?
                ORDER BY ordinal ASC
                """,
                (session["session_id"],),
            ).fetchall()
            for message in message_rows:
                text = str(message["text"] or "")
                if not message_matches_terms(
                    text,
                    query=query,
                    file_contains=file_contains,
                    command_contains=command_contains,
                    error_contains=error_contains,
                    error_only=error_only,
                ):
                    continue
                search_terms = [
                    term
                    for term in [query, file_contains, command_contains, error_contains]
                    if term
                ]
                snippet = make_snippet(text, search_terms or tokenize_search_text(text)[:1])
                results.append(
                    {
                        "session_id": session["session_id"],
                        "started_at": session.get("started_at") or "",
                        "cwd": session.get("cwd") or "",
                        "title": session.get("title") or "",
                        "summary": session.get("summary") or "",
                        "decision_summary": session.get("decision_summary") or "",
                        "tool_names": row_json_list(session, "tool_names"),
                        "files_touched": row_json_list(session, "files_touched"),
                        "commands_seen": row_json_list(session, "commands_seen"),
                        "error_signatures": row_json_list(session, "error_signatures"),
                        "project_groups": row_to_groups(session),
                        "message_ordinal": message["ordinal"],
                        "message_role": message["role"],
                        "message_kind": message["kind"],
                        "snippet": snippet,
                        "full_text": text,
                        "transcript_path": session.get("file_path") or "",
                        "obsidian_note_path": session.get("obsidian_note_path") or "",
                        "obsidian_uri": session.get("obsidian_uri") or "",
                        "match_score": snippet_score(
                            text,
                            query=query,
                            file_contains=file_contains,
                            command_contains=command_contains,
                            error_contains=error_contains,
                            role=message["role"],
                            kind=message["kind"],
                        ),
                    }
                )

        results.sort(
            key=lambda item: (
                -int(item.get("match_score", 0)),
                str(item.get("started_at") or ""),
                int(item.get("message_ordinal") or 0),
            )
        )
        return results[:limit]


def summarize_last_time(
    cwd: str | None = None,
    query: str | None = None,
    limit: int = 5,
    project_group: str | None = None,
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
) -> dict[str, Any]:
    context = related_sessions(
        cwd=cwd,
        query=query,
        limit=limit,
        project_group=project_group,
        tool_name=tool_name,
        file_contains=file_contains,
        command_contains=command_contains,
        error_contains=error_contains,
    )
    sessions = context.get("sessions", [])
    if not sessions:
        return {
            **context,
            "headline": "No prior project memory matched.",
            "decision_summary": "",
            "top_tools": [],
            "top_files": [],
            "top_commands": [],
            "top_errors": [],
        }

    lead = sessions[0]
    decision_lines = [
        str(session.get("decision_summary") or "").strip()
        for session in sessions
        if str(session.get("decision_summary") or "").strip()
    ]
    top_tools = [item for item, _ in Counter(
        tool
        for session in sessions
        for tool in session.get("tool_names", [])
    ).most_common(6)]
    top_files = [item for item, _ in Counter(
        file_path
        for session in sessions
        for file_path in session.get("files_touched", [])
    ).most_common(6)]
    top_commands = [item for item, _ in Counter(
        command
        for session in sessions
        for command in session.get("commands_seen", [])
    ).most_common(5)]
    top_errors = [item for item, _ in Counter(
        error
        for session in sessions
        for error in session.get("error_signatures", [])
    ).most_common(5)]

    headline = f"Most relevant prior session: {lead.get('title') or lead.get('session_id')}."
    if context.get("project_group"):
        headline += f" Project group: {context['project_group']}."
    decision_summary = trim_text(" | ".join(unique_preserve_order(decision_lines)[:3]), MAX_SUMMARY_TEXT)
    return {
        **context,
        "headline": headline,
        "decision_summary": decision_summary,
        "top_tools": top_tools,
        "top_files": top_files,
        "top_commands": top_commands,
        "top_errors": top_errors,
        "lead_session_id": lead.get("session_id"),
        "lead_obsidian_uri": lead.get("obsidian_uri"),
    }


def build_session_note_markdown(parsed: ParsedSession) -> str:
    frontmatter = [
        "---",
        f"session_id: {parsed.session_id}",
        f"aliases: {json.dumps([parsed.session_id])}",
        f"started_at: {parsed.started_at}",
        f"cwd: \"{parsed.cwd.replace('\"', '\\\"')}\"",
        f"source: {parsed.source}",
        f"model: {parsed.model}",
        f"transcript_path: \"{parsed.file_path.replace('\"', '\\\"')}\"",
        f"project_groups: {json.dumps(parsed.project_groups)}",
        f"tools: {json.dumps(parsed.tool_names)}",
        f"files_touched: {json.dumps(parsed.files_touched)}",
        f"commands_seen: {json.dumps(parsed.commands_seen)}",
        f"error_signatures: {json.dumps(parsed.error_signatures)}",
        "---",
        "",
    ]
    lines = frontmatter
    lines.append(f"# {parsed.title}")
    lines.append("")
    lines.append("## Summary")
    lines.append(parsed.summary or "No summary available.")
    lines.append("")
    lines.append("## Decision")
    lines.append(parsed.decision_summary or "No decision summary available.")
    lines.append("")
    lines.append("## Tools")
    lines.append(", ".join(parsed.tool_names) if parsed.tool_names else "None")
    lines.append("")
    lines.append("## Files")
    if parsed.files_touched:
        lines.extend(f"- `{file_path}`" for file_path in parsed.files_touched)
    else:
        lines.append("None")
    lines.append("")
    lines.append("## Commands")
    if parsed.commands_seen:
        lines.extend(f"- `{command}`" for command in parsed.commands_seen)
    else:
        lines.append("None")
    lines.append("")
    lines.append("## Errors")
    if parsed.error_signatures:
        lines.extend(f"- {error}" for error in parsed.error_signatures)
    else:
        lines.append("None")
    lines.append("")
    lines.append("## Transcript")
    lines.append("")
    for index, message in enumerate(parsed.messages, start=1):
        lines.append(f"### {index:03d} {message['role']} / {message['kind']}")
        lines.append("")
        lines.append("```text")
        lines.append(message["text"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def sync_session_to_obsidian(parsed: ParsedSession) -> None:
    if not obsidian_enabled() or not parsed.obsidian_note_path:
        return
    note_path = Path(parsed.obsidian_note_path)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(build_session_note_markdown(parsed), encoding="utf-8")


def sync_sessions_to_obsidian(parsed_sessions: list[ParsedSession]) -> None:
    for parsed in parsed_sessions:
        sync_session_to_obsidian(parsed)


def delete_session_from_obsidian(note_path: str) -> None:
    if not note_path:
        return
    path = Path(note_path)
    if not path.exists():
        return
    path.unlink(missing_ok=True)


def cleanup_stale_obsidian_session_notes(expected_note_paths: list[str]) -> None:
    if not obsidian_enabled():
        return
    sessions_root = obsidian_root_dir() / "Sessions"
    if not sessions_root.exists():
        return
    expected = {
        str(Path(note_path))
        for note_path in expected_note_paths
        if note_path
    }
    for path in sessions_root.rglob("*.md"):
        if str(path) in expected:
            continue
        path.unlink(missing_ok=True)


def write_obsidian_index_notes() -> None:
    if not obsidian_enabled():
        return
    root = obsidian_root_dir()
    root.mkdir(parents=True, exist_ok=True)
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT session_id, started_at, title, cwd, project_groups, obsidian_note_path
            FROM sessions
            ORDER BY started_at DESC
            LIMIT 50
            """
        ).fetchall()
    lines = ["# Codex Mem Index", "", "## Recent Sessions", ""]
    for row in rows:
        note_path = str(row["obsidian_note_path"] or "")
        title = str(row["title"] or row["session_id"])
        started_at = str(row["started_at"] or "")
        cwd = str(row["cwd"] or "")
        groups = ", ".join(row_to_groups(row))
        if note_path:
            note_link = Path(note_path)
            try:
                wiki_target = note_link.relative_to(root).with_suffix("").as_posix()
            except ValueError:
                wiki_target = note_link.stem
            lines.append(f"- [[{wiki_target}|{title}]]")
        else:
            lines.append(f"- {title}")
        lines.append(f"  started_at: {started_at}")
        if groups:
            lines.append(f"  groups: {groups}")
        if cwd:
            lines.append(f"  cwd: `{cwd}`")
    (root / "Index.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def obsidian_status() -> dict[str, Any]:
    settings = get_runtime_settings()
    root = obsidian_root_dir()
    note_count = 0
    if root.exists():
        note_count = sum(1 for _ in root.rglob("*.md"))
    return {
        "enabled": settings["enable_obsidian"],
        "vault_path": str(settings["obsidian_vault_path"]),
        "folder": settings["obsidian_folder"],
        "root_path": str(root),
        "index_path": str(root / "Index.md"),
        "note_count": note_count,
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
        "session_roots": [str(path) for path in get_runtime_settings()["session_roots"]],
        "database_path": str(DB_PATH),
        "project_groups_path": str(get_runtime_settings()["groups_path"]),
        "project_group_count": len(list_project_groups()),
        "chroma": chroma_status(),
        "obsidian": obsidian_status(),
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
                "name": "research-project",
                "description": "Merge related workspaces into one memory space.",
                "patterns": [
                    "OneDrive - Example Organization\\Research\\Project\\raw",
                    "OneDrive - Example Organization\\Research\\Project\\processed"
                ],
                "aliases": ["research", "project"]
            }
        ]
    }
    path.write_text(json.dumps(example, indent=2) + "\n", encoding="utf-8")
    clear_group_cache()
    return path
