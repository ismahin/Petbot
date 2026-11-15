param([switch]$Background)
$ErrorActionPreference = 'Stop'
$aibiPidFile = Join-Path $PSScriptRoot 'private/server.pid'
if (Test-Path -LiteralPath $aibiPidFile) {
    $aibiRunning = Get-Process -Id ([int](Get-Content -LiteralPath $aibiPidFile)) -ErrorAction SilentlyContinue
    if ($aibiRunning -and $aibiRunning.Path -eq (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')) {
        throw 'Deskter server is already running. Use server/stop.ps1 before restarting.'
    }
}
$aibiPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$aibiSettings = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'private\config.json') -Raw | ConvertFrom-Json
if ($aibiSettings.tts_backend -ne 'mithi') {throw 'Only Mithi is installed.'}
if ($aibiSettings.tts_backend -eq 'mithi') {
    & (Join-Path $PSScriptRoot 'mithi.ps1')
    $mithiReady=$false
    for($mithiAttempt=0;$mithiAttempt -lt 90;$mithiAttempt++) {
        try {
            if((Invoke-RestMethod 'http://127.0.0.1:1925/health' -TimeoutSec 2).ready) {$mithiReady=$true;break}
        } catch {Start-Sleep -Milliseconds 1000}
    }
    if(-not $mithiReady) {throw 'Mithi did not become ready; inspect logs/mithi.err.log'}
}
$aibiArguments = @('-m','uvicorn','gateway:app','--host','0.0.0.0','--port',"$($aibiSettings.port)",'--ssl-keyfile','private/server.key','--ssl-certfile','private/server.crt','--no-access-log','--ws-max-size','65536')
if ($Background) {
    $aibiLogs = Join-Path $PSScriptRoot 'logs'
    New-Item -ItemType Directory -Force -Path $aibiLogs | Out-Null
    $aibiProcess = Start-Process -FilePath $aibiPython -ArgumentList $aibiArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $aibiLogs 'server.out.log') -RedirectStandardError (Join-Path $aibiLogs 'server.err.log')
    $aibiProcess.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'private/server.pid')
    "Started Deskter server process $($aibiProcess.Id)"
} else {
    Push-Location $PSScriptRoot
    try { & $aibiPython @aibiArguments } finally { Pop-Location }
}
