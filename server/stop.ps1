$ErrorActionPreference = 'Stop'
$aibiPidFile = Join-Path $PSScriptRoot 'private/server.pid'
if (Test-Path -LiteralPath $aibiPidFile) {
$aibiServerId = [int](Get-Content -LiteralPath $aibiPidFile)
$aibiServer = Get-CimInstance Win32_Process -Filter "ProcessId=$aibiServerId"
if ($aibiServer) {
$aibiExpected = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($aibiServer.ExecutablePath -ne $aibiExpected -or $aibiServer.CommandLine -notlike '*uvicorn gateway:app*') {
    throw 'Saved PID no longer belongs to this server; refusing to stop it.'
}
# The Windows venv launcher starts a child Python process; stop this process tree.
& taskkill /PID $aibiServerId /T /F
if ($LASTEXITCODE -ne 0) { throw 'Could not stop the server process tree.' }
} else { 'Server is already stopped.' }
} else { 'No saved server process.' }
$aibiSettings = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'private/config.json') -Raw | ConvertFrom-Json
if ($aibiSettings.tts_backend -eq 'mithi') { & (Join-Path $PSScriptRoot 'mithi.ps1') -Stop }
