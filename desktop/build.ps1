# Builds frontend -> backend sidecar -> Tauri installers.   Usage: powershell -File desktop\build.ps1
# Extra args go to build-backend.py (e.g. --entry some\wrapper.py).
$ErrorActionPreference = 'Stop'
$desktop = $PSScriptRoot
$root = Split-Path $desktop
$backendArgs = $args

function Step([string]$dir, [scriptblock]$cmd) {
    Push-Location $dir
    try { & $cmd; if ($LASTEXITCODE) { throw "failed in ${dir}: $cmd" } } finally { Pop-Location }
}

Step "$root\frontend" { npm ci }
Step "$root\frontend" { npm run build }
Step $root { python "$desktop\build-backend.py" @backendArgs }
Step $desktop { npm ci }
Step $desktop { npx tauri build }

Write-Host "`nInstallers:"
Get-ChildItem "$desktop\src-tauri\target\release\bundle" -Recurse -Include *.exe, *.msi |
    ForEach-Object { "{0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB) }
