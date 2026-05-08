$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "Codex Mem Autostart.lnk"
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source

if (-not $pythonw) {
  $pythonw = (Get-Command python.exe -ErrorAction Stop).Source
}

$watcherPath = Join-Path $repoRoot "scripts\windows_autostart_watcher.py"
$arguments = "`"$watcherPath`" --repo-root `"$repoRoot`" --dashboard-url http://127.0.0.1:37801 --port 37801"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $repoRoot
$shortcut.WindowStyle = 7
$shortcut.Description = "Start Codex Mem dashboard and companion when Codex opens"
$shortcut.Save()

Write-Output "Installed Codex Mem autostart shortcut:"
Write-Output $shortcutPath
