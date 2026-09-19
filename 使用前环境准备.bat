@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "SETUP_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "SETUP_PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%SETUP_PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\prepare_environment.ps1"
if errorlevel 1 goto :error
pause
exit /b 0
:error
echo [MaaSOW] Failed. Review the error above, then retry this script.
pause
exit /b 1
