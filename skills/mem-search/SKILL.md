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

1. Use `search_sessions` for exact or keyword-heavy lookups.
2. Use `hybrid_search_sessions` when the user is asking semantically and wording may differ from the original session.
3. Use `related_sessions` or `startup_context` when beginning work in a project and you want the most relevant prior context quickly.
4. Use `search_transcript_snippets` when the user wants the exact text, error, command, or file reference from a prior session.
5. Use `summarize_last_time` when the user asks “what did we decide last time?”
6. Use `recent_sessions` when the user asks about the last few sessions or when the query is vague.
7. Use `get_session` only after narrowing to one or a few session IDs.

## Tool Guide

### `search_sessions`

Use for keyword or topic search.

Arguments:

- `query` - required search text
- `limit` - default 10, max 25
- `cwd_contains` - optional path substring filter
- `days` - optional lookback window
- `tool_name` - optional tool filter
- `file_contains` - optional file filter
- `command_contains` - optional command filter
- `error_contains` - optional error filter

### `recent_sessions`

Use for recency-based browsing.

Arguments:

- `limit` - default 10, max 25
- `cwd_contains` - optional path substring filter
- `project_group` - optional merged project group filter

### `hybrid_search_sessions`

Use for semantic or fuzzy lookups when exact keyword search may miss relevant work.

Arguments:

- `query` - required natural-language query
- `limit` - default 10, max 25
- `cwd_contains` - optional path substring filter
- `days` - optional lookback window
- `project_group` - optional merged project group filter
- `tool_name` - optional tool filter
- `file_contains` - optional file filter
- `command_contains` - optional command filter
- `error_contains` - optional error filter

### `get_session`

Use to inspect one indexed session after filtering.

Arguments:

- `session_id` - required full session ID
- `max_messages` - default 24, max 100

### `startup_context`

Use when starting a task in a known workspace and you want recent or relevant memory immediately.

Arguments:

- `cwd` - optional current working directory
- `query` - optional natural-language task description
- `limit` - default 5
- `project_group` - optional merged project group filter
- `tool_name` - optional tool filter
- `file_contains` - optional file filter
- `command_contains` - optional command filter
- `error_contains` - optional error filter

### `related_sessions`

Use for “related sessions for current folder/project” style recall.

### `search_transcript_snippets`

Use when the user wants the exact snippet plus a transcript path or Obsidian note link.

Arguments:

- `query` - optional keyword or phrase
- `limit` - default 10, max 25
- `cwd_contains` - optional path filter
- `days` - optional lookback window
- `project_group` - optional merged project group filter
- `tool_name` - optional tool filter
- `file_contains` - optional file filter
- `command_contains` - optional command filter
- `error_contains` - optional error filter
- `error_only` - restrict to error-like transcript lines

### `summarize_last_time`

Use when the user asks what was decided, changed, or learned last time.

### `list_project_groups`

Use to inspect configured merged-memory groups.

### `memory_status`

Use to verify database counts, Chroma availability, and config file paths.

## Notes

- The index is local and built from `~/.codex/sessions`.
- Chroma is optional and only used when `CODEX_MEM_ENABLE_CHROMA=1` and `chromadb` is installed.
- Project groups let multiple related folders share one memory space.
- Obsidian-compatible markdown notes are exported automatically unless disabled.
- The newest session data is refreshed automatically at session boundaries.
- If a result looks stale, rerun the lookup. The tools auto-refresh incrementally.
