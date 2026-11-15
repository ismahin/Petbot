param(
    [ValidateSet('groq')][string]$Provider='groq',
    [ValidatePattern('^[a-zA-Z0-9_./-]{1,120}$')][string]$GroqModel='openai/gpt-oss-120b'
)
$ErrorActionPreference='Stop'
$aibiMutex=New-Object System.Threading.Mutex($false,'Local\DeskterVoiceSwitch')
if (-not $aibiMutex.WaitOne(0)) { $aibiMutex.Dispose(); throw 'Another Deskter switch is running.' }
try {
    $aibiPath=Join-Path $PSScriptRoot 'private/config.json'
    $aibiOriginal=[System.IO.File]::ReadAllText($aibiPath)
    $aibiSettings=$aibiOriginal | ConvertFrom-Json
    if ($Provider -eq 'groq' -and -not $env:GROQ_API_KEY -and -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'private/groq.key'))) {
        throw 'Store the Groq key in private/groq.key or GROQ_API_KEY first.'
    }
    & (Join-Path $PSScriptRoot 'stop.ps1')
    try {
        $aibiSettings | Add-Member -NotePropertyName llm_provider -NotePropertyValue $Provider -Force
        $aibiSettings | Add-Member -NotePropertyName groq_model -NotePropertyValue $GroqModel -Force
        [System.IO.File]::WriteAllText($aibiPath,($aibiSettings | ConvertTo-Json -Depth 20)+[Environment]::NewLine,(New-Object System.Text.UTF8Encoding($false)))
        & (Join-Path $PSScriptRoot 'start.ps1') -Background
        & (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'voice_status.py') --wait 180
        if ($LASTEXITCODE -ne 0) { throw 'New LLM gateway failed readiness.' }
        "Selected LLM provider: $Provider."
    } catch {
        $aibiFailure=$_
        Write-Warning 'LLM switch failed; restoring the original configuration.'
        & (Join-Path $PSScriptRoot 'stop.ps1')
        [System.IO.File]::WriteAllText($aibiPath,$aibiOriginal,(New-Object System.Text.UTF8Encoding($false)))
        & (Join-Path $PSScriptRoot 'start.ps1') -Background
        & (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'voice_status.py') --wait 180
        throw $aibiFailure
    }
} finally { $aibiMutex.ReleaseMutex();$aibiMutex.Dispose() }
