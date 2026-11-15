param([switch]$Upload, [string]$Port = 'COM3')
$ErrorActionPreference = 'Stop'
$aibiCli = Join-Path $env:LOCALAPPDATA 'Programs\ArduinoCLI\arduino-cli.exe'
if (-not (Test-Path -LiteralPath $aibiCli)) { $aibiCli = (Get-Command arduino-cli -ErrorAction Stop).Source }
$aibiFqbn = 'esp32:esp32:XIAO_ESP32S3:PSRAM=opi,USBMode=hwcdc,CDCOnBoot=default,PartitionScheme=default_8MB,UploadSpeed=115200'
$aibiSketch = Join-Path $PSScriptRoot 'AibiFaceDetector'
$aibiBuild = Join-Path $PSScriptRoot 'build'
$aibiSavedErrorPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue' # Windows PowerShell treats native stderr warnings as ErrorRecords.
& $aibiCli compile --fqbn $aibiFqbn --build-path $aibiBuild --warnings default $aibiSketch
$aibiCompileExit = $LASTEXITCODE
$ErrorActionPreference = $aibiSavedErrorPreference
if ($aibiCompileExit -ne 0) { throw 'Arduino compilation failed' }
if ($Upload) {
    $aibiSdk = Join-Path $env:LOCALAPPDATA 'Arduino15\packages\esp32\tools\esp32-arduino-libs\idf-release_v5.1-632e0c2a\esp32s3'
    $aibiSpeech = Join-Path $aibiSdk 'esp_sr\srmodels.bin'
    $aibiEsptool = Join-Path $env:LOCALAPPDATA 'Arduino15\packages\esp32\tools\esptool_py\4.6\esptool.exe'
    if ((Get-Item -LiteralPath $aibiSpeech).Length -gt 0x260000) { throw 'Speech image exceeds the XIAO model partition' }
    if ((Get-Item -LiteralPath (Join-Path $aibiBuild 'AibiFaceDetector.ino.bin')).Length -gt 0x400000) { throw 'Application exceeds custom 4 MB app partition' }
    & $aibiEsptool --chip esp32s3 --port $Port --baud 115200 --before default_reset --after hard_reset --no-stub write_flash 0x410000 $aibiSpeech
    if ($LASTEXITCODE -ne 0) { throw 'Speech model upload failed' }
    & $aibiCli upload --fqbn $aibiFqbn --port $Port --input-dir $aibiBuild --upload-property 'upload.flags=--no-stub' $aibiSketch
    if ($LASTEXITCODE -ne 0) { throw 'Arduino upload failed' }
}
