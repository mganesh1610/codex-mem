$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dashboardUrl = if ($args.Count -gt 0) { $args[0] } else { "http://127.0.0.1:37801" }

Set-Location $repoRoot
python .\scripts\windows_companion.py --dashboard-url $dashboardUrl
