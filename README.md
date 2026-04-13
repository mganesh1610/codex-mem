# Codex Mem

`codex-mem` is a local-first Codex plugin for searching prior Codex sessions on
your machine. It was conceptually inspired by
[`claude-mem`](https://github.com/thedotmack/claude-mem), but it is built with
Codex for a personal Codex-only workflow and now supports both a fast SQLite
index and an optional Chroma semantic layer.

This repository is intended to be a clean-room implementation, not a fork of
`claude-mem`. See [NOTICE.md](./NOTICE.md) for the provenance note.

No source code, assets, or directories from `claude-mem` are included in this
repository.

## What It Does

- Scans `~/.codex/sessions/**/*.jsonl`
- Builds a searchable SQLite index under `~/.codex/memories/codex-mem/`
- Optionally syncs indexed sessions into Chroma for semantic retrieval
- Exposes MCP tools for keyword search, hybrid search, startup context, recency, and per-session drill-down
- Supports merged project memory through configurable project groups
- Refreshes the index on `SessionStart` and `SessionEnd`

## What It Does Not Do

- No external AI summarization or compression
- No web UI

## Tools

- `search_sessions`
- `hybrid_search_sessions`
- `recent_sessions`
- `get_session`
- `startup_context`
- `list_project_groups`
- `memory_status`

## Repository Layout

- `.codex-plugin/plugin.json` - plugin manifest
- `.mcp.json` - MCP server wiring
- `hooks.json` - session lifecycle hooks
- `scripts/` - MCP server, SQLite index logic, project groups, and optional Chroma sync
- `skills/mem-search/SKILL.md` - usage guidance for Codex
- `NOTICE.md` - provenance and licensing note

## Local Runtime Files

- Session transcripts: `~/.codex/sessions/`
- Index database: `~/.codex/memories/codex-mem/memory.sqlite3`
- Project groups config: `~/.codex/memories/codex-mem/project_groups.json`
- Optional Chroma path: `~/.codex/memories/codex-mem/chroma/`

## Optional Chroma Setup

If you want semantic search in addition to SQLite/FTS search:

```powershell
pip install -r requirements-chroma.txt
```

Then enable it before starting Codex:

```powershell
$env:CODEX_MEM_ENABLE_CHROMA='1'
```

Optional settings:

- `CODEX_MEM_CHROMA_PATH` - custom local persistent path
- `CODEX_MEM_CHROMA_COLLECTION` - collection name
- `CODEX_MEM_CHROMA_HOST` / `CODEX_MEM_CHROMA_PORT` - use a running Chroma server instead of local persistence

The first Chroma-backed rebuild downloads the default local embedding model once,
then reuses it from cache for future runs.

## Project Group Memory

You can merge related folders into one memory space:

```powershell
python ./scripts/mcp_server.py init-project-groups
```

That writes a template config to `~/.codex/memories/codex-mem/project_groups.json`.
Once configured, you can search with a `project_group` filter or let
`startup_context` infer the group from the current working directory.

## Manual Commands

```powershell
python ./scripts/mcp_server.py rebuild
python ./scripts/mcp_server.py search "nested cross validation"
python ./scripts/mcp_server.py hybrid-search "how did we solve transcript parsing"
python ./scripts/mcp_server.py startup-context --cwd "C:\path\to\project"
python ./scripts/mcp_server.py status
python ./scripts/mcp_server.py session 019b2045-cec6-7e13-8c2f-b2d5d4c598d4
```
