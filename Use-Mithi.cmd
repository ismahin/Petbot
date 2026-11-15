@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0server\start.ps1" -Background
pause
