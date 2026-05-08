# Codex Mem

`codex-mem` is a local-first Codex plugin for searching prior Codex sessions on
your machine. It was conceptually inspired by
[`claude-mem`](https://github.com/thedotmack/claude-mem), but it is built with
Codex for a personal Codex-only workflow and now supports a fast SQLite index,
optional Chroma semantic search, transcript snippet recall, and an
Obsidian-compatible markdown view plus a standalone local dashboard.

This repository is intended to be a clean-room implementation, not a fork of
`claude-mem`. See [NOTICE.md](./NOTICE.md) for the provenance note.

No source code, assets, or directories from `claude-mem` are included in this
repository.

## What It Does

- Scans `~/.codex/sessions/**/*.jsonl`
- Builds a searchable SQLite index under `~/.codex/memories/codex-mem/`
- Optionally syncs indexed sessions into Chroma for semantic retrieval
- Exposes MCP tools for keyword search, hybrid search, related-session recall, exact transcript snippets, and per-session drill-down
- Supports merged project memory through configurable project groups
- Extracts files, commands, errors, and last-time decisions from prior sessions
- Exports indexed sessions into an Obsidian-compatible markdown vault with note links
- Serves a responsive local web UI for session search, filters, snippets, and session inspection
- Lets you select project memory rows plus local files/images into a compact context bundle for Codex chat
- Refreshes the index on `SessionStart` and `SessionEnd`

## What It Does Not Do

- No external AI summarization or compression
- No cloud upload of your Codex transcripts; memory stays on your machine unless
  you point it at your own synced folders

## Quick Start

### 1. Clone the public repo

```powershell
git clone https://github.com/mganesh1610/codex-mem.git
cd codex-mem
```

### 2. Use Python 3.10 or newer

Codex Mem uses only the Python standard library for the core SQLite index,
MCP server, dashboard, and Windows companion.

```powershell
python --version
```

Optional but recommended:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Build the memory index

```powershell
python ./scripts/mcp_server.py rebuild
```

This reads local Codex session transcripts from `~/.codex/sessions/` and writes
the searchable index to `~/.codex/memories/codex-mem/`.

### 4. Open the local dashboard

```powershell
python ./scripts/mcp_server.py serve-ui --open-browser
```

Default URL:

```text
http://127.0.0.1:37801
```

Open that URL in the Codex right-side browser pane when you want project memory,
file/image selection, and compact context handoff beside the chat.

### 5. Add startup instructions to a project

Put this in a project-level `AGENTS.md` when you want Codex to load project
memory automatically at the start of a new thread:

```md
# Codex Mem

At the start of a new project thread, use the `codex-mem` plugin to call
`get_project_brief` for the current working directory before doing project
work. Use the brief as background context, but do not paste it to the user
unless asked.
```

If you also use dashboard-selected startup context, set `CODEX_MEM_HOME` to the
clone path and add a startup command that consumes the transient selection file.
For this repository itself, that command is:

```powershell
python .\scripts\consume_selected_context.py
```

For another project, use an absolute path or a `CODEX_MEM_HOME` helper:

```powershell
$codexMemRoot = if ($env:CODEX_MEM_HOME) { $env:CODEX_MEM_HOME } else { "C:\path\to\codex-mem" }
python (Join-Path $codexMemRoot "scripts\consume_selected_context.py")
```

The selected-context file is transient. It is consumed once and cleared so old
dashboard selections do not leak into the next thread.

## Install As A Local Codex Plugin

For local development, keep the repository in a stable folder and point Codex at
the plugin directory. The repository includes:

- `.codex-plugin/plugin.json` for plugin metadata
- `.mcp.json` for the `codex-mem` MCP server
- `hooks.json` for rebuild hooks
- `skills/mem-search/SKILL.md` for Codex usage guidance

After enabling the local plugin, start a new Codex thread in a project and ask
for prior context. The preferred tool flow is:

1. `get_project_brief` / `startup_context` for a compact project brief.
2. `search_sessions` for topic lookup.
3. `recent_sessions` for recency browsing.
4. `get_session` only after narrowing to a specific session.

## Dashboard Workflow

1. Start the dashboard:

   ```powershell
   python ./scripts/mcp_server.py serve-ui --open-browser
   ```

2. Use the left project rail to choose one or more indexed projects.
3. Select memory rows with **Use in context**.
4. Select referenced project files or images in **Artifacts**.
5. Click **Use** or **Copy for chat**.
6. Paste the compact bundle into Codex, or let the startup consumer ingest the
   selected bundle automatically on the next thread.

The dashboard is intentionally token-friendly. It sends summaries, decisions,
session IDs, and selected file paths instead of dumping full transcripts.

## Windows Companion And Autostart

The optional Windows companion provides a small on-screen control while Codex is
active. It can copy the current context pack, then hide in the system tray.

Start it manually:

```powershell
.\scripts\start_windows_companion.ps1
```

Install automatic startup:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_windows_autostart.ps1
```

Remove automatic startup:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\uninstall_windows_autostart.ps1
```

The watcher starts with Windows, waits until Codex opens, then launches the
dashboard and companion.

## Tools

- `search_sessions`
- `hybrid_search_sessions`
- `search_transcript_snippets`
- `recent_sessions`
- `get_session`
- `startup_context`
- `related_sessions`
- `summarize_last_time`
- `list_project_groups`
- `memory_status`

## Repository Layout

- `.codex-plugin/plugin.json` - plugin manifest
- `.mcp.json` - MCP server wiring
- `hooks.json` - session lifecycle hooks
- `scripts/` - MCP server, SQLite index logic, project groups, and optional Chroma sync
- `web/` - static dashboard client served by the local Python dashboard
- `skills/mem-search/SKILL.md` - usage guidance for Codex
- `NOTICE.md` - provenance and licensing note

## Local Runtime Files

- Session transcripts: `~/.codex/sessions/`
- Index database: `~/.codex/memories/codex-mem/memory.sqlite3`
- Project groups config: `~/.codex/memories/codex-mem/project_groups.json`
- Optional Chroma path: `~/.codex/memories/codex-mem/chroma/`
- Obsidian vault export: `~/.codex/memories/codex-mem/obsidian-vault/`

### Extra Session Roots

By default, Codex Mem indexes the current machine's `~/.codex/sessions/`.
To include Codex chats copied or synced from another computer, point
`CODEX_MEM_EXTRA_SESSION_ROOTS` at one or more cloud-synced session folders.
Use semicolons between paths on Windows:

```powershell
$env:CODEX_MEM_EXTRA_SESSION_ROOTS="C:\path\to\Cloud\Other-PC\.codex\sessions;C:\path\to\Cloud\Laptop\.codex\sessions"
python ./scripts/mcp_server.py rebuild
```

The dashboard groups projects by cloud-relative path when it recognizes Dropbox
or OneDrive folders, so the same project can stay grouped even when different
machines use different user-profile prefixes.

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

## Obsidian Markdown View

Every rebuild also exports session notes into an Obsidian-compatible vault at:

`~/.codex/memories/codex-mem/obsidian-vault/`

You can open that folder directly as an Obsidian vault, or use the `obsidian_uri`
returned by snippet and session results. Optional settings:

- `CODEX_MEM_ENABLE_OBSIDIAN` - set to `0` to disable note export
- `CODEX_MEM_OBSIDIAN_VAULT_PATH` - custom vault root path
- `CODEX_MEM_OBSIDIAN_FOLDER` - note folder name inside the vault root

The vault includes one note per indexed session and an `Index.md` note for quick browsing.

## Local Dashboard

You can launch the interactive browser locally:

```powershell
python ./scripts/mcp_server.py serve-ui --open-browser
```

Useful options:

- `--cwd` - pre-scope the dashboard to a folder
- `--project-group` - start inside a merged project group
- `--port` - choose a custom local port

The dashboard is intentionally separate from the Obsidian vault:

- Obsidian remains the durable markdown archive
- the dashboard is the interactive browser for search, snippets, filters, file/image selection, and session inspection

The right-side **Context Pack** panel is built for token-efficient handoff back into Codex:

- select memory rows with **Use in context**
- select files or images from the scoped file catalog
- click **Copy for chat** to copy a compact prompt containing selected decisions, session IDs, and local file paths

The local web page cannot directly type into the Codex chat box, so the bundle is copied to the clipboard for a fast paste. If browser clipboard permissions are blocked, the dashboard also writes through the local server and shows a selectable handoff text box.

The dashboard includes a **Startup context** toggle. When enabled, the page auto-selects the top recent memory rows for the current scope so **Copy for chat** is immediately ready. The setting is stored in `~/.codex/memories/codex-mem/dashboard_settings.json`.

On page load, the dashboard shows a compact startup pop-up with the same toggle and a **Copy + close** action. Use it while composing the first Codex message: copy the context pack, paste it into chat, press Enter, and the pop-up collapses back to the sidebar workflow.

Selected dashboard context is also written to
`~/.codex/memories/codex-mem/selected_startup_context.md`. `AGENTS.md` stays
stable and instructs the startup agent to call the normal project brief first,
then run `python .\scripts\consume_selected_context.py`. That command prints
the selected context once, deletes the transient file, writes a dashboard reset
signal, and flips the dashboard startup toggle off. The right-side dashboard
polls for that reset signal and clears the checked memory/file rows, so the next
thread falls back to the normal project-brief-only behavior unless the dashboard
or companion arms new selected context again.

Codex Mem can rebuild memory on `SessionStart`, but the current Codex app does not expose a plugin hook that can force-open a localhost page in the right pane before the first chat message. Keep the dashboard server running and open `http://127.0.0.1:37801` in the side pane; the startup toggle prepares the context once the page is loaded.

### Windows Companion

For a native overlay outside the browser sandbox, run the Windows companion app:

```powershell
.\scripts\start_windows_companion.ps1
```

If PowerShell script execution is blocked, use:

```powershell
.\scripts\start_windows_companion.cmd
```

The companion uses only the Python standard library. It watches the foreground
window title, shows a small always-on-top control when Codex is active, copies
the startup context pack to the Windows clipboard, and posts heartbeat/copy
events to the dashboard through `/api/companion-event`. The dashboard shows
whether the companion is connected beside the startup toggle. Minimize, close,
or **Hide** sends the companion to the Windows system tray; click the tray icon
to restore it.

To start this stack automatically, install the Windows Startup watcher:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_windows_autostart.ps1
```

The installed watcher starts silently when Windows signs in, waits until a
Codex window appears, then launches the dashboard and companion. Remove it with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\uninstall_windows_autostart.ps1
```

## Manual Commands

```powershell
python ./scripts/mcp_server.py rebuild
python ./scripts/mcp_server.py search "nested cross validation"
python ./scripts/mcp_server.py hybrid-search "how did we solve transcript parsing"
python ./scripts/mcp_server.py search-snippets --query "database is locked"
python ./scripts/mcp_server.py startup-context --cwd "C:\path\to\project"
python ./scripts/mcp_server.py related-sessions --cwd "C:\path\to\project" --query "Azure auth bug"
python ./scripts/mcp_server.py summarize-last-time --cwd "C:\path\to\project"
python ./scripts/mcp_server.py status
python ./scripts/mcp_server.py session 019b2045-cec6-7e13-8c2f-b2d5d4c598d4
python ./scripts/mcp_server.py serve-ui --cwd "C:\path\to\project" --open-browser
```
