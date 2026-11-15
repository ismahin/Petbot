$ErrorActionPreference='Stop'
$mithiEnv=Join-Path $env:LOCALAPPDATA 'Deskter/venvs/mithi-py312'
$mithiPython=Join-Path $mithiEnv 'Scripts/python.exe'
$mithiBase=(& py -3.12 -c 'import sys;print(sys.executable)').Trim()
if($LASTEXITCODE -ne 0) {throw 'Install Python 3.12 first; Misaki 0.9.4 requires Python below 3.13'}
& uv venv --python $mithiBase --allow-existing $mithiEnv
if($LASTEXITCODE -ne 0) {throw 'Mithi environment setup failed'}
& uv pip install --python $mithiPython torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu
if($LASTEXITCODE -ne 0) {throw 'CPU PyTorch install failed'}
& uv pip install --python $mithiPython -r (Join-Path $PSScriptRoot 'mithi-requirements.txt')
if($LASTEXITCODE -ne 0) {throw 'Mithi dependencies failed'}
$mithiPreviousVenv=$env:VIRTUAL_ENV
$env:VIRTUAL_ENV=$mithiEnv
try { & $mithiPython -m spacy download en_core_web_sm } finally {$env:VIRTUAL_ENV=$mithiPreviousVenv}
if($LASTEXITCODE -ne 0) {throw 'English G2P model install failed'}
& (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'fetch_mithi.py')
if($LASTEXITCODE -ne 0) {throw 'Mithi model verification failed'}
