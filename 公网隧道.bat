@echo off
setlocal
chcp 65001 >nul
title Nehchat Agent - Public Tunnel
cd /d "%~dp0"

set "PY=python"
if exist "%~dp0backend\.venv\Scripts\python.exe" set "PY=%~dp0backend\.venv\Scripts\python.exe"

:: 1. Locate cloudflared (project root first, then PATH), download if missing
set "CF=%~dp0cloudflared.exe"
if not exist "%CF%" (
    for /f "delims=" %%i in ('where cloudflared 2^>nul') do set "CF=%%i"
)

if not exist "%CF%" (
    echo [1/4] cloudflared not found, downloading...
    curl.exe -L --fail --connect-timeout 15 --max-time 600 -o "%~dp0cloudflared.exe" "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    if errorlevel 1 (
        echo [ERROR] Download failed. Download cloudflared-windows-amd64.exe manually from
        echo         https://github.com/cloudflare/cloudflared/releases/latest
        echo         and save it as: %~dp0cloudflared.exe
        pause
        exit /b 1
    )
    set "CF=%~dp0cloudflared.exe"
)
echo [1/4] cloudflared is ready

:: 2. Start backend only when port 8000 is free
echo [2/4] Checking port 8000...
"%SystemRoot%\System32\netstat.exe" -ano | "%SystemRoot%\System32\findstr.exe" "LISTENING" | "%SystemRoot%\System32\findstr.exe" ":8000" >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Port 8000 is already in use, exposing the existing service.
) else (
    echo [2/4] Starting backend service...
    pushd "%~dp0backend"
    start "Nehchat Backend" /min cmd /k ""%PY%" -m uvicorn main:app --host 127.0.0.1 --port 8000 --log-level info"
    popd
)

:: 3. Wait until the service responds (account login protects all data)
set "HTTP_CODE="
set "TRIES=0"
:probe
set "HTTP_CODE="
for /f "delims=" %%c in ('curl.exe -s -o NUL -w "%%{http_code}" --max-time 5 http://127.0.0.1:8000/api/auth/status 2^>nul') do set "HTTP_CODE=%%c"
if not "%HTTP_CODE%"=="000" if not "%HTTP_CODE%"=="" goto :probe_done
set /a TRIES+=1
if %TRIES% lss 4 (
    "%SystemRoot%\System32\timeout.exe" /t 3 >nul
    goto :probe
)
:probe_done

if "%HTTP_CODE%"=="000" goto :backend_down
if "%HTTP_CODE%"=="" goto :backend_down
echo [3/4] Service is responding. Account login is required for all data.

"%SystemRoot%\System32\findstr.exe" /b /c:"WEB_USER=" "%~dp0.env" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Extra Basic Auth layer is enabled via WEB_USER/WEB_PASSWORD.
) else (
    echo [INFO] Tip: for an extra auth layer, set WEB_USER / WEB_PASSWORD in .env.
)

echo [4/4] Starting Cloudflare quick tunnel...
echo.
echo   Look for the public URL below, it looks like: https://xxxx.trycloudflare.com
echo   Keep this window open. Closing it stops the tunnel.
echo.
"%CF%" tunnel --url http://127.0.0.1:8000 --no-autoupdate

echo.
echo Tunnel stopped.
pause
exit /b 0

:backend_down
echo [ERROR] The service is not responding on port 8000.
echo         Check the minimized "Nehchat Backend" window for startup errors.
pause
exit /b 1
