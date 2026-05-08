$ErrorActionPreference = "Stop"

$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "Codex Mem Autostart.lnk"

if (Test-Path -LiteralPath $shortcutPath) {
  Remove-Item -LiteralPath $shortcutPath
  Write-Output "Removed Codex Mem autostart shortcut:"
  Write-Output $shortcutPath
} else {
  Write-Output "Codex Mem autostart shortcut was not installed."
}
