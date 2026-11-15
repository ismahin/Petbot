param([switch]$Stop)
$ErrorActionPreference='Stop'
$mithiPython=Join-Path $env:LOCALAPPDATA 'Deskter/venvs/mithi-py312/Scripts/python.exe'
$mithiPidFile=Join-Path $PSScriptRoot 'private/mithi.pid'
if(Test-Path -LiteralPath $mithiPidFile) {
    $mithiOwnedId=[int](Get-Content -LiteralPath $mithiPidFile)
    $mithiProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$mithiOwnedId"
    if($mithiProcess) {
        if($mithiProcess.ExecutablePath -ne $mithiPython -or $mithiProcess.CommandLine -notlike '*uvicorn mithi_worker:app*') {throw 'Saved Mithi PID is not owned by this project'}
        if($Stop) {
            & taskkill /PID $mithiOwnedId /T /F
            if($LASTEXITCODE -ne 0) {throw 'Could not stop the owned Mithi process'}
        } else {'Mithi worker is already running.'}
        return
    }
}
if($Stop) {'Mithi worker is already stopped.';return}
if(-not (Test-Path -LiteralPath $mithiPython)) {throw 'Install the isolated Mithi environment first; see MITHI.md'}
$mithiProcess=Start-Process -FilePath $mithiPython -ArgumentList @('-m','uvicorn','mithi_worker:app','--host','127.0.0.1','--port','1925','--no-access-log') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'logs/mithi.out.log') -RedirectStandardError (Join-Path $PSScriptRoot 'logs/mithi.err.log')
$mithiProcess.Id | Set-Content -LiteralPath $mithiPidFile
"Started Mithi process $($mithiProcess.Id) on loopback 1925."
