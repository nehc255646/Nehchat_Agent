@echo off
setlocal
chcp 65001 >nul
set "PY=python"
if exist "%~dp0backend\.venv\Scripts\python.exe" set "PY=%~dp0backend\.venv\Scripts\python.exe"
cd /d "%~dp0"

:: 1. Check Python
"%PY%" --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found.
    pause
    exit /b 1
)
echo [1/4] Python is ready

:: 2. Install backend dependencies
echo [2/4] Installing backend dependencies...
"%PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Initializing Python package tools...
    "%PY%" -m ensurepip --upgrade >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Could not initialize pip.
        pause
        exit /b 1
    )
)
"%PY%" -m pip install -q -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] Backend dependency installation failed.
    pause
    exit /b 1
)

:: 3. Build frontend
echo [3/4] Checking frontend...
node --version >nul 2>&1
if %errorlevel% equ 0 (
    echo    Building frontend...
    cd frontend
    if not exist "node_modules" call npm install --no-audit --no-fund
    call npm run build
    if errorlevel 1 (
        echo [ERROR] Frontend build failed.
        cd /d "%~dp0"
        pause
        exit /b 1
    )
    cd /d "%~dp0"
    echo [3/4] Frontend build completed
) else (
    echo [3/4] Node.js not found, skipping frontend build
)

:: 4. Start server in this console. Closing the window stops uvicorn and its reload child.
echo [4/4] Starting server...
cd /d "%~dp0backend"
start "" /min cmd /c "%SystemRoot%\System32\timeout.exe /t 3 >nul & start http://localhost:8000"

echo ========================================
echo   Server started. Visit http://localhost:8000
echo   Close this window to stop the service.
echo ========================================

"%PY%" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload --log-level info

echo.
echo Service stopped.
pause
endlocal

