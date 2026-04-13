# Codex Mem

`codex-mem` is a local-first Codex plugin for searching prior Codex sessions on
your machine. It was conceptually inspired by
[`claude-mem`](https://github.com/thedotmack/claude-mem), but it is built for a
Codex-only workflow and uses only Python's standard library.

This repository is intended to be a clean-room implementation, not a fork of
`claude-mem`. See [NOTICE.md](./NOTICE.md) for the provenance note.

## What It Does

- Scans `~/.codex/sessions/**/*.jsonl`
- Builds a searchable SQLite index under `~/.codex/memories/codex-mem/`
- Exposes MCP tools for search, recency, and per-session drill-down
- Refreshes the index on `SessionStart` and `SessionEnd`

## What It Does Not Do

- No external AI summarization or compression
- No embeddings or vector store
- No web UI

## Tools

- `search_sessions`
- `recent_sessions`
- `get_session`

## Repository Layout

- `.codex-plugin/plugin.json` - plugin manifest
- `.mcp.json` - MCP server wiring
- `hooks.json` - session lifecycle hooks
- `scripts/` - MCP server and SQLite index logic
- `skills/mem-search/SKILL.md` - usage guidance for Codex
- `NOTICE.md` - provenance and licensing note

## Local Runtime Files

- Session transcripts: `~/.codex/sessions/`
- Index database: `~/.codex/memories/codex-mem/memory.sqlite3`

## Manual Commands

```powershell
python ./scripts/mcp_server.py rebuild
python ./scripts/mcp_server.py search "nested cross validation"
python ./scripts/mcp_server.py session 019b2045-cec6-7e13-8c2f-b2d5d4c598d4
```
