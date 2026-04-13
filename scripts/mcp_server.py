from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from memory_store import (
    get_session,
    get_startup_context,
    hybrid_search_sessions,
    list_project_groups,
    memory_status,
    recent_sessions,
    related_sessions,
    rebuild_index,
    search_transcript_snippets,
    search_sessions,
    summarize_last_time,
    write_project_groups_example,
)


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "codex-mem"
SERVER_VERSION = "0.3.0"


TOOLS = [
    {
        "name": "search_sessions",
        "description": "Keyword and full-text search over indexed Codex sessions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic or keywords to search for."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
                "cwd_contains": {"type": "string", "description": "Optional working-directory substring filter."},
                "days": {"type": "integer", "minimum": 1, "description": "Optional lookback window in days."},
                "project_group": {"type": "string", "description": "Optional merged project group or alias."},
                "tool_name": {"type": "string", "description": "Optional tool filter such as shell_command or apply_patch."},
                "file_contains": {"type": "string", "description": "Optional file path/name filter."},
                "command_contains": {"type": "string", "description": "Optional shell command substring filter."},
                "error_contains": {"type": "string", "description": "Optional error substring filter."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "hybrid_search_sessions",
        "description": "Hybrid keyword + Chroma semantic search. Falls back gracefully if Chroma is disabled.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language memory query."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
                "cwd_contains": {"type": "string", "description": "Optional working-directory substring filter."},
                "days": {"type": "integer", "minimum": 1, "description": "Optional lookback window in days."},
                "project_group": {"type": "string", "description": "Optional merged project group or alias."},
                "tool_name": {"type": "string", "description": "Optional tool filter such as shell_command or apply_patch."},
                "file_contains": {"type": "string", "description": "Optional file path/name filter."},
                "command_contains": {"type": "string", "description": "Optional shell command substring filter."},
                "error_contains": {"type": "string", "description": "Optional error substring filter."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "recent_sessions",
        "description": "List the most recent indexed Codex sessions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
                "cwd_contains": {"type": "string", "description": "Optional working-directory substring filter."},
                "project_group": {"type": "string", "description": "Optional merged project group or alias."},
                "tool_name": {"type": "string", "description": "Optional tool filter such as shell_command or apply_patch."},
                "file_contains": {"type": "string", "description": "Optional file path/name filter."},
                "command_contains": {"type": "string", "description": "Optional shell command substring filter."},
                "error_contains": {"type": "string", "description": "Optional error substring filter."},
            },
        },
    },
    {
        "name": "get_session",
        "description": "Get details and message excerpts for one indexed session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Full session ID from a search result."},
                "max_messages": {"type": "integer", "minimum": 1, "maximum": 100, "default": 24},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "startup_context",
        "description": "Find the most relevant recent memory for the current project or merged project group.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Current working directory."},
                "query": {"type": "string", "description": "Optional natural-language task description."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                "project_group": {"type": "string", "description": "Optional merged project group or alias."},
                "tool_name": {"type": "string", "description": "Optional tool filter such as shell_command or apply_patch."},
                "file_contains": {"type": "string", "description": "Optional file path/name filter."},
                "command_contains": {"type": "string", "description": "Optional shell command substring filter."},
                "error_contains": {"type": "string", "description": "Optional error substring filter."},
            },
        },
    },
    {
        "name": "related_sessions",
        "description": "Show the most relevant sessions for the current folder or merged project group.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Current working directory."},
                "query": {"type": "string", "description": "Optional natural-language task description."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                "project_group": {"type": "string", "description": "Optional merged project group or alias."},
                "tool_name": {"type": "string", "description": "Optional tool filter such as shell_command or apply_patch."},
                "file_contains": {"type": "string", "description": "Optional file path/name filter."},
                "command_contains": {"type": "string", "description": "Optional shell command substring filter."},
                "error_contains": {"type": "string", "description": "Optional error substring filter."},
            },
        },
    },
    {
        "name": "search_transcript_snippets",
        "description": "Search exact transcript snippets and return the matching text plus transcript and Obsidian links.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional keyword or phrase to find in transcript text."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
                "cwd_contains": {"type": "string", "description": "Optional working-directory substring filter."},
                "days": {"type": "integer", "minimum": 1, "description": "Optional lookback window in days."},
                "project_group": {"type": "string", "description": "Optional merged project group or alias."},
                "tool_name": {"type": "string", "description": "Optional tool filter such as shell_command or apply_patch."},
                "file_contains": {"type": "string", "description": "Optional file path/name filter."},
                "command_contains": {"type": "string", "description": "Optional shell command substring filter."},
                "error_contains": {"type": "string", "description": "Optional error substring filter."},
                "error_only": {"type": "boolean", "description": "Restrict results to error-like transcript lines."}
            }
        },
    },
    {
        "name": "summarize_last_time",
        "description": "Summarize what was decided last time for a folder, project group, or task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Current working directory."},
                "query": {"type": "string", "description": "Optional natural-language task description."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                "project_group": {"type": "string", "description": "Optional merged project group or alias."},
                "tool_name": {"type": "string", "description": "Optional tool filter such as shell_command or apply_patch."},
                "file_contains": {"type": "string", "description": "Optional file path/name filter."},
                "command_contains": {"type": "string", "description": "Optional shell command substring filter."},
                "error_contains": {"type": "string", "description": "Optional error substring filter."}
            }
        },
    },
    {
        "name": "list_project_groups",
        "description": "List configured project groups that merge memory across related workspaces.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "memory_status",
        "description": "Show index counts, Chroma status, and project-group configuration paths.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def parse_tool_names(raw_value: Any) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        try:
            decoded = json.loads(raw_value)
            if isinstance(decoded, list):
                return [str(item) for item in decoded if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return []


def parse_project_groups(raw_value: Any) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        try:
            decoded = json.loads(raw_value)
            if isinstance(decoded, list):
                return [str(item) for item in decoded if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return []


def parse_string_list(raw_value: Any) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        try:
            decoded = json.loads(raw_value)
            if isinstance(decoded, list):
                return [str(item) for item in decoded if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return []


def unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def format_session_rows(rows: list[dict[str, Any]], show_scores: bool = False) -> str:
    if not rows:
        return "No matching sessions."
    lines: list[str] = []
    for row in rows:
        tool_names = parse_tool_names(row.get("tool_names"))
        project_groups = parse_project_groups(row.get("project_groups"))
        files_touched = parse_string_list(row.get("files_touched"))
        commands_seen = parse_string_list(row.get("commands_seen"))
        error_signatures = parse_string_list(row.get("error_signatures"))
        lines.append(f"session_id: {row['session_id']}")
        lines.append(f"started_at: {row.get('started_at') or ''}")
        lines.append(f"cwd: {row.get('cwd') or ''}")
        lines.append(f"title: {row.get('title') or ''}")
        if project_groups:
            lines.append(f"project_groups: {', '.join(project_groups)}")
        if tool_names:
            lines.append(f"tools: {', '.join(tool_names)}")
        if files_touched:
            lines.append(f"files: {', '.join(files_touched[:5])}")
        if commands_seen:
            lines.append(f"commands: {', '.join(commands_seen[:3])}")
        if error_signatures:
            lines.append(f"errors: {', '.join(error_signatures[:3])}")
        if row.get("decision_summary"):
            lines.append(f"decision: {row['decision_summary']}")
        if show_scores:
            if row.get("search_sources"):
                lines.append(f"search_sources: {', '.join(row['search_sources'])}")
            if row.get("hybrid_score") is not None:
                lines.append(f"hybrid_score: {float(row['hybrid_score']):.4f}")
        if row.get("obsidian_uri"):
            lines.append(f"obsidian_uri: {row['obsidian_uri']}")
        if row.get("summary"):
            lines.append(f"summary: {row['summary']}")
        lines.append("")
    return "\n".join(lines).strip()


def format_session_detail(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "Session not found."
    project_groups = parse_project_groups(payload.get("project_groups"))
    tool_names = parse_string_list(payload.get("tool_names"))
    files_touched = parse_string_list(payload.get("files_touched"))
    commands_seen = parse_string_list(payload.get("commands_seen"))
    error_signatures = parse_string_list(payload.get("error_signatures"))
    lines = [
        f"session_id: {payload['session_id']}",
        f"started_at: {payload.get('started_at') or ''}",
        f"cwd: {payload.get('cwd') or ''}",
        f"source: {payload.get('source') or ''}",
        f"model: {payload.get('model') or ''}",
        f"title: {payload.get('title') or ''}",
        f"summary: {payload.get('summary') or ''}",
        f"decision_summary: {payload.get('decision_summary') or ''}",
        f"message_count: {payload.get('total_messages') or 0}",
    ]
    if project_groups:
        lines.append(f"project_groups: {', '.join(project_groups)}")
    if tool_names:
        lines.append(f"tools: {', '.join(tool_names)}")
    if files_touched:
        lines.append(f"files: {', '.join(files_touched)}")
    if commands_seen:
        lines.append(f"commands: {', '.join(commands_seen)}")
    if error_signatures:
        lines.append(f"errors: {', '.join(error_signatures)}")
    if payload.get("file_path"):
        lines.append(f"transcript_path: {payload['file_path']}")
    if payload.get("obsidian_note_path"):
        lines.append(f"obsidian_note_path: {payload['obsidian_note_path']}")
    if payload.get("obsidian_uri"):
        lines.append(f"obsidian_uri: {payload['obsidian_uri']}")
    lines.extend(["", "messages:"])
    for message in payload.get("messages", []):
        prefix = f"{message['ordinal']:03d} {message['role']}/{message['kind']}"
        lines.append(f"{prefix}: {message['text']}")
    return "\n".join(lines).strip()


def format_project_groups(groups: list[dict[str, Any]]) -> str:
    if not groups:
        return "No project groups configured."
    lines: list[str] = []
    for group in groups:
        lines.append(f"name: {group['name']}")
        if group.get("description"):
            lines.append(f"description: {group['description']}")
        lines.append(f"patterns: {', '.join(group.get('patterns', []))}")
        aliases = group.get("aliases", [])
        if aliases:
            lines.append(f"aliases: {', '.join(aliases)}")
        lines.append("")
    return "\n".join(lines).strip()


def format_status(payload: dict[str, Any]) -> str:
    chroma = payload.get("chroma", {})
    obsidian = payload.get("obsidian", {})
    lines = [
        f"total_sessions: {payload.get('total_sessions')}",
        f"total_messages: {payload.get('total_messages')}",
        f"latest_session_started_at: {payload.get('latest_session_started_at') or ''}",
        f"session_root: {payload.get('session_root') or ''}",
        f"database_path: {payload.get('database_path') or ''}",
        f"project_groups_path: {payload.get('project_groups_path') or ''}",
        f"project_group_count: {payload.get('project_group_count')}",
        "",
        "chroma:",
        f"  enabled: {chroma.get('enabled')}",
        f"  available: {chroma.get('available')}",
        f"  mode: {chroma.get('mode') or ''}",
        f"  collection: {chroma.get('collection') or ''}",
    ]
    if chroma.get("path"):
        lines.append(f"  path: {chroma['path']}")
    if chroma.get("host"):
        lines.append(f"  host: {chroma['host']}:{chroma.get('port')}")
    if chroma.get("error"):
        lines.append(f"  error: {chroma['error']}")
    lines.extend(
        [
            "",
            "obsidian:",
            f"  enabled: {obsidian.get('enabled')}",
            f"  vault_path: {obsidian.get('vault_path') or ''}",
            f"  folder: {obsidian.get('folder') or ''}",
            f"  root_path: {obsidian.get('root_path') or ''}",
            f"  index_path: {obsidian.get('index_path') or ''}",
            f"  note_count: {obsidian.get('note_count')}",
        ]
    )
    return "\n".join(lines).strip()


def build_startup_brief(payload: dict[str, Any]) -> str:
    sessions = payload.get("sessions") or []
    if not sessions:
        if payload.get("project_group"):
            return f"No prior sessions matched for project group '{payload['project_group']}'."
        return "No prior sessions matched this working directory yet."

    lead = sessions[0]
    common_tools = unique_preserve_order(
        tool
        for session in sessions
        for tool in parse_tool_names(session.get("tool_names"))
    )
    lines = [f"Top memory: {lead.get('title') or lead.get('session_id')}."] 
    if payload.get("project_group"):
        lines.append(f"Using merged memory group: {payload['project_group']}.")
    if common_tools:
        lines.append(f"Common tools in related work: {', '.join(common_tools[:5])}.")
    if len(sessions) > 1:
        related_titles = [
            str(session.get("title") or session.get("session_id"))
            for session in sessions[1:3]
        ]
        lines.append(f"Also relevant: {'; '.join(related_titles)}.")
    if lead.get("decision_summary"):
        lines.append(f"Latest decision: {lead['decision_summary']}.")
    lines.append(f"Next step: inspect session {lead.get('session_id')} for full context.")
    return " ".join(lines)


def format_snippet_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No matching transcript snippets."
    lines: list[str] = []
    for row in rows:
        lines.append(f"session_id: {row['session_id']}")
        lines.append(f"started_at: {row.get('started_at') or ''}")
        lines.append(f"title: {row.get('title') or ''}")
        lines.append(f"message: {row.get('message_ordinal')} {row.get('message_role')}/{row.get('message_kind')}")
        lines.append(f"snippet: {row.get('snippet') or ''}")
        if row.get("transcript_path"):
            lines.append(f"transcript_path: {row['transcript_path']}")
        if row.get("obsidian_note_path"):
            lines.append(f"obsidian_note_path: {row['obsidian_note_path']}")
        if row.get("obsidian_uri"):
            lines.append(f"obsidian_uri: {row['obsidian_uri']}")
        lines.append("")
    return "\n".join(lines).strip()


def format_last_time(payload: dict[str, Any]) -> str:
    lines = [
        f"headline: {payload.get('headline') or ''}",
        f"project_group: {payload.get('project_group') or ''}",
        f"lead_session_id: {payload.get('lead_session_id') or ''}",
    ]
    if payload.get("lead_obsidian_uri"):
        lines.append(f"lead_obsidian_uri: {payload['lead_obsidian_uri']}")
    if payload.get("decision_summary"):
        lines.append(f"decision_summary: {payload['decision_summary']}")
    if payload.get("top_tools"):
        lines.append(f"top_tools: {', '.join(payload['top_tools'])}")
    if payload.get("top_files"):
        lines.append(f"top_files: {', '.join(payload['top_files'])}")
    if payload.get("top_commands"):
        lines.append(f"top_commands: {', '.join(payload['top_commands'])}")
    if payload.get("top_errors"):
        lines.append(f"top_errors: {', '.join(payload['top_errors'])}")
    lines.append("")
    lines.append("sessions:")
    lines.append(format_session_rows(payload.get("sessions", []), show_scores=True))
    return "\n".join(lines).strip()


def format_startup_context(payload: dict[str, Any]) -> str:
    brief = build_startup_brief(payload)
    lines = [
        f"cwd: {payload.get('cwd') or ''}",
        f"project_group: {payload.get('project_group') or ''}",
    ]
    inferred_groups = payload.get("inferred_groups") or []
    if inferred_groups:
        lines.append(f"inferred_groups: {', '.join(inferred_groups)}")
    lines.append("")
    lines.append(f"brief: {brief}")
    lines.append("")
    lines.append("sessions:")
    session_text = format_session_rows(payload.get("sessions", []), show_scores=True)
    lines.append(session_text)
    return "\n".join(lines).strip()


def tool_result(name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if name == "search_sessions":
        rows = search_sessions(
            query=str(arguments.get("query") or ""),
            limit=int(arguments.get("limit", 10)),
            cwd_contains=arguments.get("cwd_contains"),
            days=arguments.get("days"),
            project_group=arguments.get("project_group"),
            tool_name=arguments.get("tool_name"),
            file_contains=arguments.get("file_contains"),
            command_contains=arguments.get("command_contains"),
            error_contains=arguments.get("error_contains"),
        )
        return format_session_rows(rows), {"rows": rows}
    if name == "hybrid_search_sessions":
        rows = hybrid_search_sessions(
            query=str(arguments.get("query") or ""),
            limit=int(arguments.get("limit", 10)),
            cwd_contains=arguments.get("cwd_contains"),
            days=arguments.get("days"),
            project_group=arguments.get("project_group"),
            tool_name=arguments.get("tool_name"),
            file_contains=arguments.get("file_contains"),
            command_contains=arguments.get("command_contains"),
            error_contains=arguments.get("error_contains"),
        )
        return format_session_rows(rows, show_scores=True), {"rows": rows}
    if name == "recent_sessions":
        rows = recent_sessions(
            limit=int(arguments.get("limit", 10)),
            cwd_contains=arguments.get("cwd_contains"),
            project_group=arguments.get("project_group"),
            tool_name=arguments.get("tool_name"),
            file_contains=arguments.get("file_contains"),
            command_contains=arguments.get("command_contains"),
            error_contains=arguments.get("error_contains"),
        )
        return format_session_rows(rows), {"rows": rows}
    if name == "get_session":
        payload = get_session(
            session_id=str(arguments.get("session_id") or ""),
            max_messages=int(arguments.get("max_messages", 24)),
        )
        return format_session_detail(payload), {"session": payload}
    if name == "startup_context":
        payload = get_startup_context(
            cwd=arguments.get("cwd"),
            query=arguments.get("query"),
            limit=int(arguments.get("limit", 5)),
            project_group=arguments.get("project_group"),
            tool_name=arguments.get("tool_name"),
            file_contains=arguments.get("file_contains"),
            command_contains=arguments.get("command_contains"),
            error_contains=arguments.get("error_contains"),
        )
        payload["brief"] = build_startup_brief(payload)
        return format_startup_context(payload), payload
    if name == "related_sessions":
        payload = related_sessions(
            cwd=arguments.get("cwd"),
            query=arguments.get("query"),
            limit=int(arguments.get("limit", 5)),
            project_group=arguments.get("project_group"),
            tool_name=arguments.get("tool_name"),
            file_contains=arguments.get("file_contains"),
            command_contains=arguments.get("command_contains"),
            error_contains=arguments.get("error_contains"),
        )
        payload["brief"] = build_startup_brief(payload)
        return format_startup_context(payload), payload
    if name == "search_transcript_snippets":
        rows = search_transcript_snippets(
            query=arguments.get("query"),
            limit=int(arguments.get("limit", 10)),
            cwd_contains=arguments.get("cwd_contains"),
            days=arguments.get("days"),
            project_group=arguments.get("project_group"),
            tool_name=arguments.get("tool_name"),
            file_contains=arguments.get("file_contains"),
            command_contains=arguments.get("command_contains"),
            error_contains=arguments.get("error_contains"),
            error_only=bool(arguments.get("error_only", False)),
        )
        return format_snippet_rows(rows), {"rows": rows}
    if name == "summarize_last_time":
        payload = summarize_last_time(
            cwd=arguments.get("cwd"),
            query=arguments.get("query"),
            limit=int(arguments.get("limit", 5)),
            project_group=arguments.get("project_group"),
            tool_name=arguments.get("tool_name"),
            file_contains=arguments.get("file_contains"),
            command_contains=arguments.get("command_contains"),
            error_contains=arguments.get("error_contains"),
        )
        return format_last_time(payload), payload
    if name == "list_project_groups":
        groups = list_project_groups()
        return format_project_groups(groups), {"groups": groups}
    if name == "memory_status":
        payload = memory_status()
        return format_status(payload), payload
    raise ValueError(f"Unknown tool: {name}")


def read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def write_message(payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def write_response(message_id: Any, result: Any) -> None:
    write_message({"jsonrpc": "2.0", "id": message_id, "result": result})


def write_error(message_id: Any, code: int, message: str) -> None:
    write_message(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
    )


def run_stdio_server() -> None:
    while True:
        request = read_message()
        if request is None:
            return

        method = request.get("method")
        message_id = request.get("id")
        params = request.get("params", {})

        try:
            if method == "initialize":
                write_response(
                    message_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    },
                )
            elif method == "notifications/initialized":
                continue
            elif method == "ping":
                write_response(message_id, {})
            elif method == "tools/list":
                write_response(message_id, {"tools": TOOLS})
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                result_text, structured = tool_result(str(tool_name), dict(arguments))
                write_response(
                    message_id,
                    {
                        "content": [{"type": "text", "text": result_text}],
                        "structuredContent": structured,
                    },
                )
            else:
                write_error(message_id, -32601, f"Method not found: {method}")
        except Exception as exc:  # pragma: no cover
            write_error(message_id, -32000, str(exc))


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="codex-mem MCP server and helper CLI")
    subparsers = parser.add_subparsers(dest="command")

    rebuild_parser = subparsers.add_parser("rebuild", help="Rebuild the local session index")
    rebuild_parser.add_argument("--force", action="store_true")
    rebuild_parser.add_argument("--quiet", action="store_true")

    search_parser = subparsers.add_parser("search", help="Keyword search indexed sessions")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--cwd-contains")
    search_parser.add_argument("--days", type=int)
    search_parser.add_argument("--project-group")
    search_parser.add_argument("--tool-name")
    search_parser.add_argument("--file-contains")
    search_parser.add_argument("--command-contains")
    search_parser.add_argument("--error-contains")

    hybrid_parser = subparsers.add_parser("hybrid-search", help="Hybrid keyword plus Chroma semantic search")
    hybrid_parser.add_argument("query")
    hybrid_parser.add_argument("--limit", type=int, default=10)
    hybrid_parser.add_argument("--cwd-contains")
    hybrid_parser.add_argument("--days", type=int)
    hybrid_parser.add_argument("--project-group")
    hybrid_parser.add_argument("--tool-name")
    hybrid_parser.add_argument("--file-contains")
    hybrid_parser.add_argument("--command-contains")
    hybrid_parser.add_argument("--error-contains")

    recent_parser = subparsers.add_parser("recent", help="Show recent sessions")
    recent_parser.add_argument("--limit", type=int, default=10)
    recent_parser.add_argument("--cwd-contains")
    recent_parser.add_argument("--project-group")
    recent_parser.add_argument("--tool-name")
    recent_parser.add_argument("--file-contains")
    recent_parser.add_argument("--command-contains")
    recent_parser.add_argument("--error-contains")

    session_parser = subparsers.add_parser("session", help="Show one session")
    session_parser.add_argument("session_id")
    session_parser.add_argument("--max-messages", type=int, default=24)

    status_parser = subparsers.add_parser("status", help="Show memory and Chroma status")

    groups_parser = subparsers.add_parser("groups", help="List configured project groups")

    init_groups_parser = subparsers.add_parser("init-project-groups", help="Write an example project group config")
    init_groups_parser.add_argument("--force", action="store_true")

    startup_parser = subparsers.add_parser("startup-context", help="Show relevant recent context for a project")
    startup_parser.add_argument("--cwd")
    startup_parser.add_argument("--query")
    startup_parser.add_argument("--limit", type=int, default=5)
    startup_parser.add_argument("--project-group")
    startup_parser.add_argument("--tool-name")
    startup_parser.add_argument("--file-contains")
    startup_parser.add_argument("--command-contains")
    startup_parser.add_argument("--error-contains")

    related_parser = subparsers.add_parser("related-sessions", help="Show related sessions for the current folder or project group")
    related_parser.add_argument("--cwd")
    related_parser.add_argument("--query")
    related_parser.add_argument("--limit", type=int, default=5)
    related_parser.add_argument("--project-group")
    related_parser.add_argument("--tool-name")
    related_parser.add_argument("--file-contains")
    related_parser.add_argument("--command-contains")
    related_parser.add_argument("--error-contains")

    snippets_parser = subparsers.add_parser("search-snippets", help="Search exact transcript snippets")
    snippets_parser.add_argument("--query")
    snippets_parser.add_argument("--limit", type=int, default=10)
    snippets_parser.add_argument("--cwd-contains")
    snippets_parser.add_argument("--days", type=int)
    snippets_parser.add_argument("--project-group")
    snippets_parser.add_argument("--tool-name")
    snippets_parser.add_argument("--file-contains")
    snippets_parser.add_argument("--command-contains")
    snippets_parser.add_argument("--error-contains")
    snippets_parser.add_argument("--error-only", action="store_true")

    last_time_parser = subparsers.add_parser("summarize-last-time", help="Summarize what was decided last time")
    last_time_parser.add_argument("--cwd")
    last_time_parser.add_argument("--query")
    last_time_parser.add_argument("--limit", type=int, default=5)
    last_time_parser.add_argument("--project-group")
    last_time_parser.add_argument("--tool-name")
    last_time_parser.add_argument("--file-contains")
    last_time_parser.add_argument("--command-contains")
    last_time_parser.add_argument("--error-contains")

    return parser


def main() -> int:
    parser = build_cli()
    args = parser.parse_args()

    if not args.command:
        run_stdio_server()
        return 0

    if args.command == "rebuild":
        stats = rebuild_index(force=args.force)
        if not args.quiet:
            print(json.dumps(stats, indent=2))
        return 0

    if args.command == "search":
        text, _ = tool_result(
            "search_sessions",
            {
                "query": args.query,
                "limit": args.limit,
                "cwd_contains": args.cwd_contains,
                "days": args.days,
                "project_group": args.project_group,
                "tool_name": args.tool_name,
                "file_contains": args.file_contains,
                "command_contains": args.command_contains,
                "error_contains": args.error_contains,
            },
        )
        print(text)
        return 0

    if args.command == "hybrid-search":
        text, _ = tool_result(
            "hybrid_search_sessions",
            {
                "query": args.query,
                "limit": args.limit,
                "cwd_contains": args.cwd_contains,
                "days": args.days,
                "project_group": args.project_group,
                "tool_name": args.tool_name,
                "file_contains": args.file_contains,
                "command_contains": args.command_contains,
                "error_contains": args.error_contains,
            },
        )
        print(text)
        return 0

    if args.command == "recent":
        text, _ = tool_result(
            "recent_sessions",
            {
                "limit": args.limit,
                "cwd_contains": args.cwd_contains,
                "project_group": args.project_group,
                "tool_name": args.tool_name,
                "file_contains": args.file_contains,
                "command_contains": args.command_contains,
                "error_contains": args.error_contains,
            },
        )
        print(text)
        return 0

    if args.command == "session":
        text, _ = tool_result(
            "get_session",
            {"session_id": args.session_id, "max_messages": args.max_messages},
        )
        print(text)
        return 0

    if args.command == "status":
        text, _ = tool_result("memory_status", {})
        print(text)
        return 0

    if args.command == "groups":
        text, _ = tool_result("list_project_groups", {})
        print(text)
        return 0

    if args.command == "init-project-groups":
        path = write_project_groups_example(force=args.force)
        print(f"Wrote project group config template: {path}")
        return 0

    if args.command == "startup-context":
        text, _ = tool_result(
            "startup_context",
            {
                "cwd": args.cwd,
                "query": args.query,
                "limit": args.limit,
                "project_group": args.project_group,
                "tool_name": args.tool_name,
                "file_contains": args.file_contains,
                "command_contains": args.command_contains,
                "error_contains": args.error_contains,
            },
        )
        print(text)
        return 0

    if args.command == "related-sessions":
        text, _ = tool_result(
            "related_sessions",
            {
                "cwd": args.cwd,
                "query": args.query,
                "limit": args.limit,
                "project_group": args.project_group,
                "tool_name": args.tool_name,
                "file_contains": args.file_contains,
                "command_contains": args.command_contains,
                "error_contains": args.error_contains,
            },
        )
        print(text)
        return 0

    if args.command == "search-snippets":
        text, _ = tool_result(
            "search_transcript_snippets",
            {
                "query": args.query,
                "limit": args.limit,
                "cwd_contains": args.cwd_contains,
                "days": args.days,
                "project_group": args.project_group,
                "tool_name": args.tool_name,
                "file_contains": args.file_contains,
                "command_contains": args.command_contains,
                "error_contains": args.error_contains,
                "error_only": args.error_only,
            },
        )
        print(text)
        return 0

    if args.command == "summarize-last-time":
        text, _ = tool_result(
            "summarize_last_time",
            {
                "cwd": args.cwd,
                "query": args.query,
                "limit": args.limit,
                "project_group": args.project_group,
                "tool_name": args.tool_name,
                "file_contains": args.file_contains,
                "command_contains": args.command_contains,
                "error_contains": args.error_contains,
            },
        )
        print(text)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
