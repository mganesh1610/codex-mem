from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import webbrowser
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse
from uuid import uuid4

from memory_store import (
    DB_PATH,
    SESSION_ROOT,
    STATE_DIR,
    connect_db,
    finalize_rows,
    fts_available,
    get_chroma_components,
    get_runtime_settings,
    group_names_for_cwd,
    iso_cutoff,
    list_project_groups,
    obsidian_status,
    row_matches_filters,
    safe_fts_query,
    resolve_group_name,
    search_transcript_snippets,
)


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 37801
DEFAULT_LIMIT = 8
ACTIVITY_DAYS = 14
MAX_ASSET_ROWS = 250
MAX_PROJECT_ROWS = 250
MAX_BUNDLE_SESSIONS = 8
MAX_BUNDLE_FILES = 40
MAX_PREVIEW_BYTES = 12 * 1024 * 1024
DASHBOARD_SETTINGS_PATH = STATE_DIR / "dashboard_settings.json"
COMPANION_STATUS_PATH = STATE_DIR / "companion_status.json"
SELECTED_STARTUP_CONTEXT_PATH = STATE_DIR / "selected_startup_context.md"
SELECTED_STARTUP_CONTEXT_CLEAR_SIGNAL_PATH = STATE_DIR / "selected_startup_context_clear.json"
SELECTED_STARTUP_CONTEXT_TTL_MINUTES = 30
LINE_SUFFIX_RE = re.compile(r"^(.+?)(?::\d+){1,2}$")
PATH_WITH_TRAILING_CONTEXT_RE = re.compile(r"^(.+\.[A-Za-z0-9]{1,8})(?::\d+)?(?::.*)?$")
GIT_STATUS_PATH_RE = re.compile(r"^(?:[ MADRCU?!]{1,2}|\?\?)\s+(.+)$")
IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
CODE_EXTENSIONS = {
    ".bat",
    ".c",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
DATA_EXTENSIONS = {".csv", ".db", ".jsonl", ".parquet", ".sqlite", ".sqlite3", ".tsv", ".xlsx", ".xml"}
DOCUMENT_EXTENSIONS = {".doc", ".docx", ".pdf", ".ppt", ".pptx", ".rtf"}
IGNORED_ASSET_EXTENSIONS = {".pyc", ".pyo"}
CLOUD_MARKERS = (
    "ASU Dropbox",
    "OneDrive - Arizona State University",
    "Dropbox",
    "OneDrive",
)


def parse_string(params: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    value = params.get(key, [default])[0]
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def parse_int(params: dict[str, list[str]], key: str, default: int | None = None) -> int | None:
    raw = parse_string(params, key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def parse_bool(params: dict[str, list[str]], key: str, default: bool = False) -> bool:
    raw = parse_string(params, key)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def iso_day(value: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).date().isoformat()


def summarize_activity(rows: list[dict[str, Any]], days: int = ACTIVITY_DAYS) -> list[dict[str, Any]]:
    counts = Counter()
    for row in rows:
        day = iso_day(str(row.get("started_at") or ""))
        if day:
            counts[day] += 1
    today = datetime.now(timezone.utc).date()
    activity: list[dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        activity.append({"date": day, "count": counts.get(day, 0)})
    return activity


def parse_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not value:
        return []
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                return [str(item) for item in decoded if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return []


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def path_parts(value: str) -> list[str]:
    return [part for part in re.split(r"[\\/]+", str(value or "")) if part]


def cloud_suffix(value: str) -> str:
    parts = path_parts(value)
    lowered = [part.lower() for part in parts]
    for marker in CLOUD_MARKERS:
        marker_lower = marker.lower()
        if marker_lower in lowered:
            index = lowered.index(marker_lower)
            return "/".join(parts[index:]).lower()
    return str(value or "").lower()


def project_display_name(cwd: str) -> str:
    parts = path_parts(cwd)
    if not parts:
        return "No working directory"
    return parts[-1]


@lru_cache(maxsize=1)
def local_cloud_roots() -> tuple[Path, ...]:
    candidates: list[Path] = []
    home = Path.home()
    for marker in CLOUD_MARKERS:
        candidates.append(home / marker)
        candidates.extend((home / "ASU Dropbox").glob(f"**/{marker}") if (home / "ASU Dropbox").exists() else [])

    ordered: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = path.resolve(strict=False)
        except OSError:
            resolved = path
        key = str(resolved).lower()
        if key in seen or not path.exists():
            continue
        seen.add(key)
        ordered.append(resolved)
    return tuple(ordered)


def remap_cloud_path(path_value: str) -> str | None:
    parts = path_parts(path_value)
    lowered = [part.lower() for part in parts]
    for marker in CLOUD_MARKERS:
        marker_lower = marker.lower()
        if marker_lower not in lowered:
            continue
        marker_index = lowered.index(marker_lower)
        suffix_parts = parts[marker_index + 1:]
        for root in local_cloud_roots():
            if root.name.lower() != marker_lower:
                continue
            candidate = root.joinpath(*suffix_parts)
            if candidate.exists():
                return str(candidate.resolve(strict=False))
        for root in local_cloud_roots():
            candidate = root.joinpath(*suffix_parts)
            if candidate.exists():
                return str(candidate.resolve(strict=False))
    return None


def build_quick_summary(
    rows: list[dict[str, Any]],
    cwd: str,
    project_group: str | None,
    fallback_to_global: bool = False,
) -> dict[str, Any]:
    if not rows:
        return {
            "headline": "No indexed sessions matched this scope yet.",
            "decision_summary": "",
            "top_tools": [],
            "top_files": [],
            "top_commands": [],
            "top_errors": [],
            "sessions": [],
            "lead_session_id": None,
            "lead_obsidian_uri": None,
        }

    lead = rows[0]
    top_tools = [item for item, _ in Counter(
        tool
        for row in rows
        for tool in row.get("tool_names", [])
    ).most_common(6)]
    top_files = [item for item, _ in Counter(
        file_path
        for row in rows
        for file_path in row.get("files_touched", [])
    ).most_common(6)]
    top_commands = [item for item, _ in Counter(
        command
        for row in rows
        for command in row.get("commands_seen", [])
    ).most_common(5)]
    top_errors = [item for item, _ in Counter(
        error
        for row in rows
        for error in row.get("error_signatures", [])
    ).most_common(5)]

    decision_lines = dedupe([
        str(row.get("decision_summary") or "").strip()
        for row in rows
    ])
    joined_decisions = " | ".join(decision_lines[:3]).strip()
    if fallback_to_global:
        headline = "No direct memory for this folder yet. Showing global recent memory instead."
    elif project_group:
        headline = f"Recent memory for {project_group}."
    elif cwd:
        headline = "Recent memory for the current folder."
    else:
        headline = "Recent memory across local Codex sessions."

    return {
        "headline": headline,
        "decision_summary": joined_decisions or str(lead.get("summary") or "No decision summary available."),
        "top_tools": top_tools,
        "top_files": top_files,
        "top_commands": top_commands,
        "top_errors": top_errors,
        "sessions": rows,
        "lead_session_id": lead.get("session_id"),
        "lead_obsidian_uri": lead.get("obsidian_uri"),
    }


def serialize_session_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["tool_names"] = parse_json_list(payload.get("tool_names"))
    payload["files_touched"] = parse_json_list(payload.get("files_touched"))
    payload["commands_seen"] = parse_json_list(payload.get("commands_seen"))
    payload["error_signatures"] = parse_json_list(payload.get("error_signatures"))
    payload["project_groups"] = parse_json_list(payload.get("project_groups"))
    return payload


def quick_recent_sessions(
    limit: int = 25,
    cwd_contains: str | None = None,
    project_group: str | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 25))
    with connect_db() as conn:
        rows = conn.execute(
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
            LIMIT 100
            """
        ).fetchall()

    filtered: list[dict[str, Any]] = []
    normalized_cwd = (cwd_contains or "").lower()
    normalized_group = resolve_group_name(project_group)
    for row in rows:
        payload = serialize_session_row(row)
        if normalized_cwd and normalized_cwd not in str(payload.get("cwd") or "").lower():
            continue
        if normalized_group and normalized_group not in payload.get("project_groups", []):
            continue
        filtered.append(payload)
        if len(filtered) >= limit:
            break
    return filtered


def quick_search_sessions(
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

        where_sql = f" AND {' AND '.join(where_clauses)}" if where_clauses else ""
        fts_query = safe_fts_query(query)

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


def quick_semantic_search_sessions(
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
                [item.strip() for item in str(metadata.get("project_groups", "")).split(",") if item.strip()]
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


def quick_hybrid_search_sessions(
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
    keyword_rows = quick_search_sessions(
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
    semantic_rows = quick_semantic_search_sessions(
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
        payload["search_sources"] = ["keyword"]
        payload["hybrid_score"] = 1.0 / index
        merged[payload["session_id"]] = payload

    for index, row in enumerate(semantic_rows, start=1):
        payload = dict(row)
        session_id = payload["session_id"]
        semantic_score = float(payload.get("semantic_score", 1.0 / index))
        if session_id in merged:
            existing = merged[session_id]
            existing["search_sources"] = dedupe(existing.get("search_sources", []) + ["semantic"])
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


def quick_related_sessions(
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
        sessions = quick_hybrid_search_sessions(
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
        sessions = quick_recent_sessions(
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


def quick_summarize_last_time(
    cwd: str | None = None,
    query: str | None = None,
    limit: int = 5,
    project_group: str | None = None,
    tool_name: str | None = None,
    file_contains: str | None = None,
    command_contains: str | None = None,
    error_contains: str | None = None,
) -> dict[str, Any]:
    context = quick_related_sessions(
        cwd=cwd,
        query=query,
        limit=limit,
        project_group=project_group,
        tool_name=tool_name,
        file_contains=file_contains,
        command_contains=command_contains,
        error_contains=error_contains,
    )
    summary = build_quick_summary(
        context.get("sessions", []),
        cwd=context.get("cwd") or "",
        project_group=context.get("project_group"),
        fallback_to_global=False,
    )
    return {**context, **summary}


def quick_get_session(session_id: str, max_messages: int = 24) -> dict[str, Any] | None:
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

    payload = serialize_session_row(session_row)
    payload["messages"] = [dict(row) for row in message_rows]
    payload["total_messages"] = total_messages
    payload["source"] = session_row["source"]
    payload["model"] = session_row["model"]
    payload["obsidian_note_path"] = session_row["obsidian_note_path"]
    return payload


def dashboard_status() -> dict[str, Any]:
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
        "project_group_count": len(list_project_groups()),
        "obsidian": obsidian_status(),
    }


def dashboard_settings() -> dict[str, Any]:
    defaults = {
        "startup_context_enabled": True,
        "startup_auto_select_limit": 3,
    }
    try:
        raw = json.loads(DASHBOARD_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    return {
        "startup_context_enabled": bool(raw.get("startup_context_enabled", defaults["startup_context_enabled"])),
        "startup_auto_select_limit": max(
            1,
            min(int(raw.get("startup_auto_select_limit", defaults["startup_auto_select_limit"]) or 3), 8),
        ),
    }


def write_dashboard_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = dashboard_settings()
    if "startup_context_enabled" in payload:
        current["startup_context_enabled"] = bool(payload["startup_context_enabled"])
    if "startup_auto_select_limit" in payload:
        current["startup_auto_select_limit"] = max(1, min(int(payload["startup_auto_select_limit"] or 3), 8))
    DASHBOARD_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_SETTINGS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def companion_status() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    defaults = {
        "connected": False,
        "last_seen_at": None,
        "codex_focused": False,
        "window_title": "",
        "overlay_visible": False,
        "last_event": None,
        "events": [],
    }
    try:
        raw = json.loads(COMPANION_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    last_seen_at = str(raw.get("last_seen_at") or "")
    connected = False
    if last_seen_at:
        try:
            parsed = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
            connected = (now - parsed.astimezone(timezone.utc)).total_seconds() < 12
        except ValueError:
            connected = False
    return {
        **defaults,
        **raw,
        "connected": connected,
    }


def write_companion_event(payload: dict[str, Any]) -> dict[str, Any]:
    current = companion_status()
    timestamp = datetime.now(timezone.utc).isoformat()
    event = {
        "type": compact_bundle_text(payload.get("type") or "event", 80),
        "at": timestamp,
        "window_title": compact_bundle_text(payload.get("window_title") or "", 180),
        "codex_focused": bool(payload.get("codex_focused")),
        "overlay_visible": bool(payload.get("overlay_visible")),
        "details": compact_bundle_text(payload.get("details") or "", 220),
    }
    events = [event, *list(current.get("events") or [])][:20]
    status = {
        "connected": True,
        "last_seen_at": timestamp,
        "codex_focused": event["codex_focused"],
        "window_title": event["window_title"],
        "overlay_visible": event["overlay_visible"],
        "last_event": event,
        "events": events,
    }
    COMPANION_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMPANION_STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def build_project_index(limit: int = MAX_PROJECT_ROWS) -> list[dict[str, Any]]:
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                session_id,
                started_at,
                cwd,
                title,
                decision_summary,
                tool_names,
                files_touched,
                project_groups
            FROM sessions
            ORDER BY started_at DESC
            LIMIT 2000
            """
        ).fetchall()

    projects: dict[str, dict[str, Any]] = {}
    for raw_row in rows:
        row = serialize_session_row(raw_row)
        cwd = str(row.get("cwd") or "").strip()
        key = cloud_suffix(cwd) if cwd else "__no_cwd__"
        project = projects.get(key)
        if project is None:
            project = {
                "id": key,
                "name": project_display_name(cwd),
                "primary_cwd": cwd,
                "cwd_variants": [],
                "session_count": 0,
                "latest_started_at": "",
                "latest_title": "",
                "latest_decision": "",
                "project_groups": [],
                "top_files": [],
                "top_tools": [],
            }
            projects[key] = project
        project["session_count"] = int(project["session_count"]) + 1
        if cwd and cwd not in project["cwd_variants"]:
            project["cwd_variants"].append(cwd)
        if str(row.get("started_at") or "") > str(project.get("latest_started_at") or ""):
            project["latest_started_at"] = row.get("started_at") or ""
            project["latest_title"] = row.get("title") or row.get("session_id") or ""
            project["latest_decision"] = row.get("decision_summary") or ""
            project["primary_cwd"] = cwd
        project["project_groups"] = dedupe(project["project_groups"] + row.get("project_groups", []))
        project["top_files"].extend(row.get("files_touched", [])[:4])
        project["top_tools"].extend(row.get("tool_names", [])[:4])

    ordered: list[dict[str, Any]] = []
    for project in projects.values():
        project["top_files"] = [item for item, _ in Counter(project["top_files"]).most_common(5)]
        project["top_tools"] = [item for item, _ in Counter(project["top_tools"]).most_common(5)]
        project["cwd_variant_count"] = len(project["cwd_variants"])
        ordered.append(project)

    ordered.sort(key=lambda item: (-int(item["session_count"]), str(item["latest_started_at"])), reverse=False)
    ordered = sorted(ordered, key=lambda item: (str(item["latest_started_at"] or "")), reverse=True)
    return ordered[: max(1, min(int(limit), MAX_PROJECT_ROWS))]


def build_overview(
    cwd: str | None,
    project_group: str | None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    effective_cwd = (cwd or "").strip()
    inferred_groups = group_names_for_cwd(effective_cwd)
    effective_group = resolve_group_name(project_group) or (inferred_groups[0] if inferred_groups else None)

    recent_rows = quick_recent_sessions(
        limit=25,
        cwd_contains=effective_cwd or None,
        project_group=effective_group,
    )
    fallback_to_global = False
    if not recent_rows and (effective_cwd or effective_group):
        recent_rows = quick_recent_sessions(limit=25)
        fallback_to_global = True

    summary = build_quick_summary(
        recent_rows[:limit],
        cwd=effective_cwd,
        project_group=effective_group,
        fallback_to_global=fallback_to_global,
    )

    top_groups = [
        {"name": name, "count": count}
        for name, count in Counter(
            group_name
            for row in recent_rows
            for group_name in row.get("project_groups", [])
        ).most_common(5)
    ]

    return {
        "cwd": effective_cwd,
        "project_group": effective_group,
        "inferred_groups": inferred_groups,
        "related": summary.get("sessions", [])[:limit],
        "recent": recent_rows[:limit],
        "summary": summary,
        "error_snippets": [],
        "activity": summarize_activity(recent_rows),
        "top_groups": top_groups,
        "fallback_to_global": fallback_to_global,
    }


def build_bootstrap(default_cwd: str | None, default_project_group: str | None) -> dict[str, Any]:
    status = dashboard_status()
    obsidian = dict(status.get("obsidian") or {})
    index_path = str(obsidian.get("index_path") or "")
    obsidian["index_uri"] = f"obsidian://open?path={quote(index_path)}" if index_path else ""
    return {
        "default_cwd": "",
        "local_cwd": default_cwd or "",
        "default_project_group": None,
        "status": {**status, "obsidian": obsidian},
        "project_groups": list_project_groups(),
        "projects": build_project_index(),
        "settings": dashboard_settings(),
        "companion": companion_status(),
        "selected_context": selected_startup_context_status(),
        "overview": build_overview(None, None),
    }


def build_filter_args(params: dict[str, list[str]]) -> dict[str, Any]:
    cwd = parse_string(params, "cwd")
    return {
        "cwd": cwd or None,
        "cwd_contains": cwd or None,
        "project_group": parse_string(params, "project_group"),
        "tool_name": parse_string(params, "tool_name"),
        "file_contains": parse_string(params, "file_contains"),
        "command_contains": parse_string(params, "command_contains"),
        "error_contains": parse_string(params, "error_contains"),
        "days": parse_int(params, "days"),
        "limit": max(1, min(parse_int(params, "limit", DEFAULT_LIMIT) or DEFAULT_LIMIT, 25)),
    }


def clean_asset_token(value: str) -> str:
    cleaned = unquote(str(value or "").strip().strip("`'\""))
    if cleaned.startswith("<") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1].strip()
    cleaned = cleaned.replace("`", "").strip()
    status_match = GIT_STATUS_PATH_RE.match(cleaned)
    if status_match:
        cleaned = status_match.group(1).strip()
    if cleaned.lower().startswith("file:///"):
        cleaned = cleaned[8:]
    elif cleaned.lower().startswith("file://"):
        cleaned = cleaned[7:]
    line_match = LINE_SUFFIX_RE.match(cleaned)
    if line_match:
        cleaned = line_match.group(1)
    context_match = PATH_WITH_TRAILING_CONTEXT_RE.match(cleaned)
    if context_match:
        cleaned = context_match.group(1)
    return cleaned.strip()


def resolve_asset_path(value: str, base_cwd: str | None = None, *, check_local: bool = True) -> tuple[str, str]:
    cleaned = clean_asset_token(value)
    if not cleaned:
        return "", ""
    lowered = cleaned.lower()
    if lowered.startswith(("http://", "https://", "obsidian://")):
        return cleaned, cleaned
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute() and base_cwd:
        candidate = Path(base_cwd).expanduser() / candidate
    try:
        resolved = str(candidate.resolve(strict=False))
    except OSError:
        resolved = str(candidate)
    if check_local and not path_exists(resolved):
        remapped = remap_cloud_path(resolved)
        if remapped:
            resolved = remapped
    return cleaned, resolved


@lru_cache(maxsize=2048)
def directory_entries(parent: str) -> frozenset[str]:
    try:
        with os.scandir(parent) as entries:
            return frozenset(entry.name.lower() for entry in entries)
    except OSError:
        return frozenset()


def cheap_path_exists(path_value: str) -> bool:
    if not path_value or path_value.lower().startswith(("http://", "https://", "obsidian://")):
        return False
    try:
        path = Path(path_value)
        return path.name.lower() in directory_entries(str(path.parent))
    except OSError:
        return False


def path_exists(path_value: str) -> bool:
    if not path_value or path_value.lower().startswith(("http://", "https://", "obsidian://")):
        return False
    try:
        return Path(path_value).exists()
    except OSError:
        return False


def path_size(path_value: str) -> int | None:
    if not path_exists(path_value):
        return None
    try:
        target = Path(path_value)
        if not target.is_file():
            return None
        return target.stat().st_size
    except OSError:
        return None


def classify_asset(path_value: str, source: str) -> str:
    extension = Path(path_value).suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in CODE_EXTENSIONS:
        return "code"
    if extension in DATA_EXTENSIONS:
        return "data"
    if extension in DOCUMENT_EXTENSIONS:
        return "document"
    return "file"


def asset_label(path_value: str, raw_value: str) -> str:
    name = Path(path_value).name if path_value else ""
    return name or Path(raw_value).name or raw_value


def should_show_asset(raw_value: str, resolved_path: str) -> bool:
    raw = str(raw_value or "").strip()
    lowered_raw = raw.lower()
    target = str(resolved_path or raw_value or "").strip()
    lowered_target = target.lower()
    extension = Path(target).suffix.lower()
    if not target or not extension:
        return False
    if extension in IGNORED_ASSET_EXTENSIONS:
        return False
    if extension not in IMAGE_EXTENSIONS | CODE_EXTENSIONS | DATA_EXTENSIONS | DOCUMENT_EXTENSIONS:
        return False
    if "\\n" in lowered_raw or "\n" in raw or "\r" in raw:
        return False
    if "*" in raw or "[" in raw or "]" in raw:
        return False
    if ".codex\\sessions" in lowered_target or ".codex/sessions" in lowered_target:
        return False
    if Path(target).name.lower().startswith("rollout-") and extension == ".jsonl":
        return False
    if "..." in raw:
        return False
    if lowered_raw.startswith(
        (
            "add a ",
            "after ",
            "await ",
            "install ",
            "return ",
            "the ",
            "program ",
            "references/",
            "code:",
        )
    ):
        return False
    if (
        "\\" not in raw
        and "/" not in raw
        and " " in raw
        and extension not in IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS
    ):
        return False
    return True


def fetch_context_session_rows(
    cwd: str | None = None,
    project_group: str | None = None,
    days: int | None = None,
    limit: int = MAX_ASSET_ROWS,
) -> list[dict[str, Any]]:
    sql_limit = max(25, min(int(limit), MAX_ASSET_ROWS))
    with connect_db() as conn:
        rows = conn.execute(
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
            (sql_limit,),
        ).fetchall()

    filtered: list[dict[str, Any]] = []
    for row in rows:
        if not row_matches_filters(
            row,
            cwd_contains=cwd,
            days=days,
            project_group=project_group,
        ):
            continue
        filtered.append(serialize_session_row(row))
    return filtered


def build_context_assets(
    cwd: str | None = None,
    project_group: str | None = None,
    days: int | None = None,
    limit: int = MAX_ASSET_ROWS,
) -> dict[str, Any]:
    rows = fetch_context_session_rows(cwd=cwd, project_group=project_group, days=days, limit=limit)
    assets: dict[str, dict[str, Any]] = {}

    def record(raw_value: str, source: str, session: dict[str, Any]) -> None:
        raw, resolved = resolve_asset_path(raw_value, session.get("cwd") or cwd, check_local=False)
        if not raw:
            return
        if not should_show_asset(raw, resolved or raw):
            return
        key = resolved.lower() if resolved else raw.lower()
        extension = Path(resolved or raw).suffix.lower()
        kind = classify_asset(resolved or raw, source)
        exists = cheap_path_exists(resolved)
        entry = assets.get(key)
        if entry is None:
            entry = {
                "id": key,
                "label": asset_label(resolved or raw, raw),
                "path": resolved or raw,
                "raw_path": raw,
                "kind": kind,
                "extension": extension,
                "exists": exists,
                "size_bytes": None,
                "sources": [],
                "count": 0,
                "last_seen": session.get("started_at") or "",
                "sessions": [],
            }
            assets[key] = entry
        entry["count"] = int(entry.get("count") or 0) + 1
        if source not in entry["sources"]:
            entry["sources"].append(source)
        session_summary = {
            "session_id": session.get("session_id"),
            "title": session.get("title") or session.get("session_id"),
            "started_at": session.get("started_at") or "",
            "cwd": session.get("cwd") or "",
        }
        if not any(item["session_id"] == session_summary["session_id"] for item in entry["sessions"]):
            entry["sessions"].append(session_summary)
        if str(session.get("started_at") or "") > str(entry.get("last_seen") or ""):
            entry["last_seen"] = session.get("started_at") or ""

    for row in rows:
        for file_path in row.get("files_touched", []):
            record(file_path, "context", row)

    ordered = sorted(
        assets.values(),
        key=lambda item: (
            item["kind"] != "image",
            -int(item.get("count") or 0),
            str(item.get("label") or "").lower(),
        ),
    )
    return {
        "items": ordered[: max(1, min(int(limit), MAX_ASSET_ROWS))],
        "session_count": len(rows),
        "image_count": sum(1 for item in ordered if item["kind"] == "image"),
        "existing_count": sum(1 for item in ordered if item["exists"]),
    }


def fetch_sessions_by_ids(session_ids: list[str]) -> list[dict[str, Any]]:
    ordered_ids = [item for item in dedupe([str(value).strip() for value in session_ids]) if item]
    if not ordered_ids:
        return []
    ordered_ids = ordered_ids[:MAX_BUNDLE_SESSIONS]
    placeholders = ",".join("?" for _ in ordered_ids)
    with connect_db() as conn:
        rows = conn.execute(
            f"""
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
            WHERE session_id IN ({placeholders})
            """,
            ordered_ids,
        ).fetchall()
    by_id = {row["session_id"]: serialize_session_row(row) for row in rows}
    return [by_id[item] for item in ordered_ids if item in by_id]


def compact_bundle_text(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def build_context_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    cwd = str(payload.get("cwd") or "").strip()
    project_group = str(payload.get("project_group") or "").strip()
    query = str(payload.get("query") or "").strip()
    project_cwds = [
        str(value).strip()
        for value in list(payload.get("project_cwds") or [])[:MAX_BUNDLE_SESSIONS]
        if str(value).strip()
    ]
    project_names = [
        str(value).strip()
        for value in list(payload.get("project_names") or [])[: len(project_cwds)]
    ]
    sessions = fetch_sessions_by_ids(list(payload.get("session_ids") or []))
    seen_session_ids = {str(session.get("session_id") or "") for session in sessions}
    if project_cwds:
        per_project_limit = max(1, min(int(payload.get("limit") or DEFAULT_LIMIT), MAX_BUNDLE_SESSIONS))
        for project_cwd in project_cwds:
            if len(sessions) >= MAX_BUNDLE_SESSIONS:
                break
            for row in fetch_context_session_rows(cwd=project_cwd, limit=per_project_limit)[:per_project_limit]:
                session_id = str(row.get("session_id") or "")
                if not session_id or session_id in seen_session_ids:
                    continue
                sessions.append(row)
                seen_session_ids.add(session_id)
                if len(sessions) >= MAX_BUNDLE_SESSIONS:
                    break
    if not sessions:
        sessions = fetch_context_session_rows(
            cwd=cwd or None,
            project_group=project_group or None,
            limit=min(int(payload.get("limit") or DEFAULT_LIMIT), MAX_BUNDLE_SESSIONS),
        )[:MAX_BUNDLE_SESSIONS]

    file_paths = [
        str(value).strip()
        for value in list(payload.get("file_paths") or [])[:MAX_BUNDLE_FILES]
        if str(value).strip()
    ]
    lines = [
        "# Codex Mem Context Pack",
        "",
        f"Scope: {'selected projects' if project_cwds else (cwd or 'global memory')}",
    ]
    if project_group:
        lines.append(f"Project group: {project_group}")
    if query:
        lines.append(f"Task/search: {query}")
    if project_cwds:
        lines.extend(["", "## Selected Projects"])
        for index, project_cwd in enumerate(project_cwds):
            label = project_names[index] if index < len(project_names) and project_names[index] else project_display_name(project_cwd)
            lines.append(f"- {compact_bundle_text(label, 100)}")
            lines.append(f"  Path: {project_cwd}")

    lines.extend(["", "## Selected Memory"])
    if sessions:
        for session in sessions:
            title = compact_bundle_text(session.get("title") or session.get("session_id"), 140)
            lines.append(f"- {session.get('started_at') or 'unknown date'} | {title}")
            if session.get("decision_summary"):
                lines.append(f"  Decision: {compact_bundle_text(session['decision_summary'])}")
            elif session.get("summary"):
                lines.append(f"  Summary: {compact_bundle_text(session['summary'])}")
            lines.append(f"  Session: {session.get('session_id')}")
            if session.get("obsidian_uri"):
                lines.append(f"  Obsidian: {session['obsidian_uri']}")
    else:
        lines.append("- No selected memory.")

    lines.extend(["", "## Selected Local Files"])
    if file_paths:
        for file_path in file_paths:
            raw, resolved = resolve_asset_path(file_path, cwd or None)
            target = resolved or raw
            kind = classify_asset(target, "context")
            exists = "exists" if path_exists(target) else "not found"
            lines.append(f"- {target} ({kind}, {exists})")
    else:
        lines.append("- No selected files.")

    lines.extend(
        [
            "",
            "Use the selected memory summaries first. Open only the listed local files when their contents are needed.",
        ]
    )
    text = "\n".join(lines).strip()
    return {
        "text": text,
        "session_count": len(sessions),
        "file_count": len(file_paths),
        "character_count": len(text),
    }


def selected_startup_context_status() -> dict[str, Any]:
    exists = SELECTED_STARTUP_CONTEXT_PATH.exists()
    modified_at = None
    age_seconds = None
    if exists:
        try:
            modified = datetime.fromtimestamp(SELECTED_STARTUP_CONTEXT_PATH.stat().st_mtime, tz=timezone.utc)
            modified_at = modified.isoformat()
            age_seconds = int((datetime.now(timezone.utc) - modified).total_seconds())
        except OSError:
            exists = False
    return {
        "exists": exists,
        "path": str(SELECTED_STARTUP_CONTEXT_PATH),
        "modified_at": modified_at,
        "age_seconds": age_seconds,
        "ttl_minutes": SELECTED_STARTUP_CONTEXT_TTL_MINUTES,
        "clear_signal": selected_startup_context_clear_signal(),
    }


def selected_startup_context_clear_signal() -> dict[str, Any] | None:
    try:
        raw = json.loads(SELECTED_STARTUP_CONTEXT_CLEAR_SIGNAL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    token = str(raw.get("token") or raw.get("cleared_at") or "")
    if not token:
        return None
    return {
        "token": token,
        "cleared_at": raw.get("cleared_at"),
        "reason": raw.get("reason"),
    }


def write_selected_startup_context_clear_signal(reason: str) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "token": f"{now.isoformat()}-{uuid4().hex[:8]}",
        "cleared_at": now.isoformat(),
        "reason": reason,
    }
    try:
        SELECTED_STARTUP_CONTEXT_CLEAR_SIGNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        SELECTED_STARTUP_CONTEXT_CLEAR_SIGNAL_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def write_selected_startup_context(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("clear") or payload.get("enabled") is False:
        try:
            SELECTED_STARTUP_CONTEXT_PATH.unlink()
        except FileNotFoundError:
            pass
        write_selected_startup_context_clear_signal("manual-clear")
        write_dashboard_settings({"startup_context_enabled": False})
        return {"selected_context": selected_startup_context_status(), "character_count": 0}

    bundle = build_context_bundle(payload)
    generated_at = datetime.now(timezone.utc)
    expires_at = generated_at + timedelta(minutes=SELECTED_STARTUP_CONTEXT_TTL_MINUTES)
    lines = [
        "<!-- codex-mem-selected-startup-context -->",
        "# Codex Mem Selected Startup Context",
        "",
        f"Generated: {generated_at.isoformat()}",
        f"Expires: {expires_at.isoformat()}",
        "",
        "Use this as temporary user-selected context in addition to the normal project brief.",
        "",
        bundle["text"],
        "",
        "After reading this selected startup context, clear it by running:",
        f"python scripts/consume_selected_context.py --clear-only --path \"{SELECTED_STARTUP_CONTEXT_PATH}\"",
        "",
    ]
    text = "\n".join(lines).strip() + "\n"
    SELECTED_STARTUP_CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SELECTED_STARTUP_CONTEXT_PATH.write_text(text, encoding="utf-8")
    status = selected_startup_context_status()
    return {
        "selected_context": status,
        "session_count": bundle["session_count"],
        "file_count": bundle["file_count"],
        "character_count": len(text),
    }


def set_system_clipboard(value: str) -> dict[str, Any]:
    text = str(value or "")
    if not text:
        return {"ok": False, "error": "Nothing to copy."}

    commands: list[list[str]] = []
    if os.name == "nt":
        clip_path = shutil.which("clip.exe") or shutil.which("clip")
        if clip_path:
            commands.append([clip_path])
    elif shutil.which("pbcopy"):
        commands.append(["pbcopy"])
    elif shutil.which("wl-copy"):
        commands.append(["wl-copy"])
    elif shutil.which("xclip"):
        commands.append(["xclip", "-selection", "clipboard"])

    if not commands:
        return {"ok": False, "error": "No system clipboard command is available."}

    last_error = ""
    for command in commands:
        kwargs: dict[str, Any] = {
            "input": text,
            "text": True,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
            "timeout": 5,
            "check": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(command, **kwargs)
            return {
                "ok": True,
                "method": Path(command[0]).name,
                "character_count": len(text),
            }
        except (OSError, subprocess.SubprocessError) as exc:
            stderr = getattr(exc, "stderr", "") or ""
            last_error = str(stderr or exc).strip()
    return {"ok": False, "error": last_error or "Clipboard command failed."}


def known_image_asset(path_value: str) -> bool:
    _, resolved = resolve_asset_path(path_value)
    if not resolved or Path(resolved).suffix.lower() not in IMAGE_EXTENSIONS or not path_exists(resolved):
        return False
    target_key = resolved.lower()
    for item in build_context_assets(limit=MAX_ASSET_ROWS)["items"]:
        if str(item.get("path") or "").lower() == target_key:
            return True
    return False


class DashboardHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        default_cwd: str | None = None,
        default_project_group: str | None = None,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.web_root = WEB_ROOT.resolve()
        self.default_cwd = (default_cwd or os.getcwd()).strip()
        inferred_groups = group_names_for_cwd(self.default_cwd)
        self.default_project_group = resolve_group_name(default_project_group) or (
            inferred_groups[0] if inferred_groups else None
        )


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: DashboardHTTPServer

    def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover
        return

    def send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")

    def json_response(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def binary_response(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=60")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def text_response(self, text: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, request_path: str) -> None:
        clean_path = unquote(request_path)
        if clean_path in {"", "/"}:
            target = self.server.web_root / "index.html"
        else:
            relative = clean_path.lstrip("/")
            target = (self.server.web_root / relative).resolve()
            if "." not in Path(relative).name:
                target = self.server.web_root / "index.html"

        if not str(target).startswith(str(self.server.web_root)) or not target.exists() or target.is_dir():
            self.text_response("Not found", status=404)
            return

        content_type, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api(parsed)
            return
        self.serve_static(parsed.path)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in {
            "/api/context-bundle",
            "/api/clipboard",
            "/api/settings",
            "/api/companion-event",
            "/api/selected-startup-context",
        }:
            self.json_response({"error": f"Unknown endpoint: {parsed.path}"}, status=404)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            content_length = 0
        if content_length > 128 * 1024:
            self.json_response({"error": "Request body is too large."}, status=413)
            return
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.json_response({"error": "Request body must be JSON."}, status=400)
            return
        if not isinstance(payload, dict):
            payload = {}
        if parsed.path == "/api/clipboard":
            result = set_system_clipboard(str(payload.get("text") or ""))
            self.json_response(result, status=200 if result.get("ok") else 500)
            return
        if parsed.path == "/api/settings":
            self.json_response({"settings": write_dashboard_settings(payload)})
            return
        if parsed.path == "/api/companion-event":
            self.json_response({"companion": write_companion_event(payload)})
            return
        if parsed.path == "/api/selected-startup-context":
            self.json_response(write_selected_startup_context(payload))
            return
        self.json_response(build_context_bundle(payload))

    def asset_preview_response(self, params: dict[str, list[str]]) -> None:
        raw_path = parse_string(params, "path")
        if not raw_path:
            self.text_response("Missing path", status=400)
            return
        _, resolved = resolve_asset_path(raw_path)
        target = Path(resolved)
        if not known_image_asset(resolved):
            self.text_response("Image is not in the indexed context catalog", status=404)
            return
        try:
            if target.stat().st_size > MAX_PREVIEW_BYTES:
                self.text_response("Image is too large to preview", status=413)
                return
            content_type, _ = mimetypes.guess_type(str(target))
            self.binary_response(target.read_bytes(), content_type or "application/octet-stream")
        except OSError as exc:
            self.text_response(str(exc), status=404)

    def handle_api(self, parsed: Any) -> None:
        params = parse_qs(parsed.query, keep_blank_values=False)
        try:
            if parsed.path == "/api/health":
                self.json_response({"ok": True})
                return

            if parsed.path == "/api/bootstrap":
                self.json_response(build_bootstrap(self.server.default_cwd, self.server.default_project_group))
                return

            if parsed.path == "/api/overview":
                cwd = parse_string(params, "cwd")
                project_group = parse_string(params, "project_group")
                limit = max(1, min(parse_int(params, "limit", DEFAULT_LIMIT) or DEFAULT_LIMIT, 25))
                self.json_response(build_overview(cwd, project_group, limit=limit))
                return

            if parsed.path == "/api/project-groups":
                self.json_response({"groups": list_project_groups()})
                return

            if parsed.path == "/api/settings":
                self.json_response({"settings": dashboard_settings()})
                return

            if parsed.path == "/api/companion-status":
                self.json_response({"companion": companion_status()})
                return

            if parsed.path == "/api/selected-startup-context":
                self.json_response({"selected_context": selected_startup_context_status()})
                return

            if parsed.path == "/api/projects":
                limit = max(1, min(parse_int(params, "limit", MAX_PROJECT_ROWS) or MAX_PROJECT_ROWS, MAX_PROJECT_ROWS))
                self.json_response({"projects": build_project_index(limit=limit)})
                return

            if parsed.path == "/api/context-assets":
                filters = build_filter_args(params)
                asset_limit = max(1, min(parse_int(params, "asset_limit", 120) or 120, MAX_ASSET_ROWS))
                self.json_response(
                    build_context_assets(
                        cwd=filters["cwd_contains"],
                        project_group=filters["project_group"],
                        days=filters["days"],
                        limit=asset_limit,
                    )
                )
                return

            if parsed.path == "/api/context-bundle":
                payload = {
                    "cwd": parse_string(params, "cwd", self.server.default_cwd),
                    "project_group": parse_string(params, "project_group", self.server.default_project_group),
                    "query": parse_string(params, "query"),
                    "project_cwds": params.get("project_cwd", []),
                    "project_names": params.get("project_name", []),
                    "session_ids": params.get("session_id", []),
                    "file_paths": params.get("file_path", []),
                    "limit": parse_int(params, "limit", DEFAULT_LIMIT) or DEFAULT_LIMIT,
                }
                self.json_response(build_context_bundle(payload))
                return

            if parsed.path == "/api/asset-preview":
                self.asset_preview_response(params)
                return

            if parsed.path == "/api/recent":
                filters = build_filter_args(params)
                rows = recent_sessions(
                    limit=filters["limit"],
                    cwd_contains=filters["cwd_contains"],
                    project_group=filters["project_group"],
                    tool_name=filters["tool_name"],
                    file_contains=filters["file_contains"],
                    command_contains=filters["command_contains"],
                    error_contains=filters["error_contains"],
                )
                self.json_response({"rows": rows})
                return

            if parsed.path == "/api/search":
                filters = build_filter_args(params)
                query = parse_string(params, "query")
                if not query:
                    self.json_response({"error": "Missing query parameter."}, status=400)
                    return
                mode = parse_string(params, "mode", "hybrid") or "hybrid"
                search_fn = quick_hybrid_search_sessions if mode == "hybrid" else quick_search_sessions
                rows = search_fn(
                    query=query,
                    limit=filters["limit"],
                    cwd_contains=filters["cwd_contains"],
                    days=filters["days"],
                    project_group=filters["project_group"],
                    tool_name=filters["tool_name"],
                    file_contains=filters["file_contains"],
                    command_contains=filters["command_contains"],
                    error_contains=filters["error_contains"],
                )
                self.json_response({"mode": mode, "query": query, "rows": rows})
                return

            if parsed.path == "/api/snippets":
                filters = build_filter_args(params)
                rows = search_transcript_snippets(
                    query=parse_string(params, "query"),
                    limit=filters["limit"],
                    cwd_contains=filters["cwd_contains"],
                    days=filters["days"],
                    project_group=filters["project_group"],
                    tool_name=filters["tool_name"],
                    file_contains=filters["file_contains"],
                    command_contains=filters["command_contains"],
                    error_contains=filters["error_contains"],
                    error_only=parse_bool(params, "error_only", False),
                )
                self.json_response({"rows": rows})
                return

            if parsed.path == "/api/related":
                filters = build_filter_args(params)
                payload = quick_related_sessions(
                    cwd=filters["cwd"],
                    query=parse_string(params, "query"),
                    limit=filters["limit"],
                    project_group=filters["project_group"],
                    tool_name=filters["tool_name"],
                    file_contains=filters["file_contains"],
                    command_contains=filters["command_contains"],
                    error_contains=filters["error_contains"],
                )
                self.json_response(payload)
                return

            if parsed.path == "/api/summary":
                filters = build_filter_args(params)
                payload = quick_summarize_last_time(
                    cwd=filters["cwd"],
                    query=parse_string(params, "query"),
                    limit=filters["limit"],
                    project_group=filters["project_group"],
                    tool_name=filters["tool_name"],
                    file_contains=filters["file_contains"],
                    command_contains=filters["command_contains"],
                    error_contains=filters["error_contains"],
                )
                self.json_response(payload)
                return

            if parsed.path.startswith("/api/session/"):
                session_id = parsed.path.removeprefix("/api/session/").strip()
                payload = quick_get_session(
                    session_id=session_id,
                    max_messages=max(1, min(parse_int(params, "max_messages", 60) or 60, 100)),
                )
                if payload is None:
                    self.json_response({"error": f"Unknown session: {session_id}"}, status=404)
                    return
                self.json_response(payload)
                return

            self.json_response({"error": f"Unknown endpoint: {parsed.path}"}, status=404)
        except Exception as exc:  # pragma: no cover
            self.json_response({"error": str(exc)}, status=500)


def serve_dashboard(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    cwd: str | None = None,
    project_group: str | None = None,
    open_browser: bool = False,
) -> int:
    server = DashboardHTTPServer(
        (host, port),
        DashboardRequestHandler,
        default_cwd=cwd,
        default_project_group=project_group,
    )
    url = f"http://{host}:{port}"
    print(f"Codex Mem dashboard listening on {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        server.server_close()
    return 0


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the Codex Mem web dashboard")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--cwd")
    parser.add_argument("--project-group")
    parser.add_argument("--open-browser", action="store_true")
    return parser


def main() -> int:
    args = build_cli().parse_args()
    return serve_dashboard(
        host=args.host,
        port=args.port,
        cwd=args.cwd,
        project_group=args.project_group,
        open_browser=args.open_browser,
    )


if __name__ == "__main__":
    raise SystemExit(main())
