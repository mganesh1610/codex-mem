---
name: mem-search
description: Search local Codex session memory from previous threads. Use when the user asks about earlier work, prior sessions, or how something was solved before.
---

# Codex Mem Search

Use the `codex-mem` MCP tools when the user asks about previous Codex work:

- "Did we already solve this?"
- "What did we do last time?"
- "Find the session where we worked on X"

## Preferred Workflow

1. Use `search_sessions` for a topic-based lookup.
2. Use `recent_sessions` when the user asks about the last few sessions or when the query is vague.
3. Use `get_session` only after narrowing to one or a few session IDs.

## Tool Guide

### `search_sessions`

Use for keyword or topic search.

Arguments:

- `query` - required search text
- `limit` - default 10, max 25
- `cwd_contains` - optional path substring filter
- `days` - optional lookback window

### `recent_sessions`

Use for recency-based browsing.

Arguments:

- `limit` - default 10, max 25
- `cwd_contains` - optional path substring filter

### `get_session`

Use to inspect one indexed session after filtering.

Arguments:

- `session_id` - required full session ID
- `max_messages` - default 24, max 100

## Notes

- The index is local and built from `~/.codex/sessions`.
- The newest session data is refreshed automatically at session boundaries.
- If a result looks stale, rerun the lookup. The tools auto-refresh incrementally.
