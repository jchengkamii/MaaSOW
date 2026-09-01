@echo off
setlocal
cd /d "%~dp0"

set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PROJECT_PYTHON%" (
    echo [MaaSOW] Creating Python 3.12 virtual environment...
    py -3.12 -m venv "%~dp0.venv"
    if errorlevel 1 goto :error
)

"%PROJECT_PYTHON%" -c "import maa" >nul 2>nul
if errorlevel 1 (
    echo [MaaSOW] Installing Python dependencies...
    "%PROJECT_PYTHON%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 goto :error
)

echo [MaaSOW] Updating MXU task cards...
"%PROJECT_PYTHON%" "%~dp0sync_mxu_interface.py"
if errorlevel 1 goto :error

if not exist "%~dp0九霄仙府自动化测试.exe" (
    echo [MaaSOW] Cannot find 九霄仙府自动化测试.exe
    goto :error
)

start "" "%~dp0九霄仙府自动化测试.exe"
exit /b 0

:error
echo.
echo [MaaSOW] Startup failed. Review the message above.
pause
exit /b 1
