@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

if not exist "%~dp0九霄小助手.exe" (
    echo [MaaSOW] Cannot find 九霄小助手.exe
    goto :error
)

rem Use the same project-local Python and native prerequisites as interface.json.
set "SETUP_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "SETUP_PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%SETUP_PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\prepare_environment.ps1"
if errorlevel 1 goto :error

start "" "%~dp0九霄小助手.exe"
exit /b 0

:error
echo.
echo [MaaSOW] Startup failed. Review the message above.
pause
exit /b 1
