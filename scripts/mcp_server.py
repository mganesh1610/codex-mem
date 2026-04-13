from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from memory_store import get_session, recent_sessions, rebuild_index, search_sessions


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "codex-mem"
SERVER_VERSION = "0.1.0"


TOOLS = [
    {
        "name": "search_sessions",
        "description": "Search indexed Codex sessions by topic or keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Topic or keywords to search for."
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 25,
                    "default": 10
                },
                "cwd_contains": {
                    "type": "string",
                    "description": "Optional working-directory substring filter."
                },
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional lookback window in days."
                }
            },
            "required": [
                "query"
            ]
        }
    },
    {
        "name": "recent_sessions",
        "description": "List the most recent indexed Codex sessions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 25,
                    "default": 10
                },
                "cwd_contains": {
                    "type": "string",
                    "description": "Optional working-directory substring filter."
                }
            }
        }
    },
    {
        "name": "get_session",
        "description": "Get details and message excerpts for one indexed session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Full session ID from search_sessions or recent_sessions."
                },
                "max_messages": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 24
                }
            },
            "required": [
                "session_id"
            ]
        }
    }
]


def format_session_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No matching sessions."
    lines: list[str] = []
    for row in rows:
        tool_names = ", ".join(json.loads(row["tool_names"])) if row.get("tool_names") else ""
        lines.append(f"session_id: {row['session_id']}")
        lines.append(f"started_at: {row.get('started_at') or ''}")
        lines.append(f"cwd: {row.get('cwd') or ''}")
        lines.append(f"title: {row.get('title') or ''}")
        if tool_names:
            lines.append(f"tools: {tool_names}")
        if row.get("summary"):
            lines.append(f"summary: {row['summary']}")
        lines.append("")
    return "\n".join(lines).strip()


def format_session_detail(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "Session not found."
    lines = [
        f"session_id: {payload['session_id']}",
        f"started_at: {payload.get('started_at') or ''}",
        f"cwd: {payload.get('cwd') or ''}",
        f"source: {payload.get('source') or ''}",
        f"model: {payload.get('model') or ''}",
        f"title: {payload.get('title') or ''}",
        f"summary: {payload.get('summary') or ''}",
        f"message_count: {payload.get('total_messages') or 0}",
        "",
        "messages:"
    ]
    for message in payload.get("messages", []):
        prefix = f"{message['ordinal']:03d} {message['role']}/{message['kind']}"
        lines.append(f"{prefix}: {message['text']}")
    return "\n".join(lines).strip()


def tool_result_text(name: str, arguments: dict[str, Any]) -> str:
    if name == "search_sessions":
        rows = search_sessions(
            query=str(arguments.get("query") or ""),
            limit=int(arguments.get("limit", 10)),
            cwd_contains=arguments.get("cwd_contains"),
            days=arguments.get("days")
        )
        return format_session_rows(rows)
    if name == "recent_sessions":
        rows = recent_sessions(
            limit=int(arguments.get("limit", 10)),
            cwd_contains=arguments.get("cwd_contains")
        )
        return format_session_rows(rows)
    if name == "get_session":
        payload = get_session(
            session_id=str(arguments.get("session_id") or ""),
            max_messages=int(arguments.get("max_messages", 24))
        )
        return format_session_detail(payload)
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
                "message": message
            }
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
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": SERVER_NAME,
                            "version": SERVER_VERSION
                        }
                    }
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
                result_text = tool_result_text(str(tool_name), dict(arguments))
                write_response(
                    message_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": result_text
                            }
                        ]
                    }
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

    search_parser = subparsers.add_parser("search", help="Search indexed sessions")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--cwd-contains")
    search_parser.add_argument("--days", type=int)

    recent_parser = subparsers.add_parser("recent", help="Show recent sessions")
    recent_parser.add_argument("--limit", type=int, default=10)
    recent_parser.add_argument("--cwd-contains")

    session_parser = subparsers.add_parser("session", help="Show one session")
    session_parser.add_argument("session_id")
    session_parser.add_argument("--max-messages", type=int, default=24)

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
        print(
            format_session_rows(
                search_sessions(
                    query=args.query,
                    limit=args.limit,
                    cwd_contains=args.cwd_contains,
                    days=args.days
                )
            )
        )
        return 0

    if args.command == "recent":
        print(
            format_session_rows(
                recent_sessions(limit=args.limit, cwd_contains=args.cwd_contains)
            )
        )
        return 0

    if args.command == "session":
        print(
            format_session_detail(
                get_session(args.session_id, max_messages=args.max_messages)
            )
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
