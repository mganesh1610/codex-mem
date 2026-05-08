# Codex Mem

At the start of a new project thread, use the `codex-mem` plugin to call
`get_project_brief` for the current working directory before doing project
work. Use the brief as background context, but do not paste it to the user
unless asked.

After the normal project brief, also run:

```powershell
python .\scripts\consume_selected_context.py
```

If that command prints selected startup context, use it silently as additional
user-selected context alongside the project brief. The command consumes and
deletes the transient selected-context file and resets the dashboard startup
selection, so no permanent instruction file changes are needed after the thread
starts.
