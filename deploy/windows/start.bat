@echo off
REM ============================================================
REM MomentumX - One-touch startup (no NSSM, manual/RDP session)
REM Starts MongoDB + FastAPI backend + built React frontend.
REM For a persistent setup that survives reboots/logouts, use
REM install_nssm_service.ps1 instead (see README.md in this folder).
REM ============================================================

set ROOT=%~dp0..\..
echo Root directory: %ROOT%

echo.
echo [1/3] Starting MongoDB...
net start MongoDB >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   MongoDB service started.
) else (
    echo   MongoDB service not found or already running - attempting mongod.exe directly...
    start "MongoDB" cmd /k "mongod --dbpath \"%ROOT%\mongodb-data\""
)

echo.
echo [2/3] Starting backend (FastAPI/uvicorn on 127.0.0.1:8001)...
start "MomentumX Backend" cmd /k "cd /d %ROOT%\backend && call venv\Scripts\activate.bat && uvicorn server:app --host 127.0.0.1 --port 8001"

echo.
echo [3/3] Building and serving frontend (http://127.0.0.1:3000)...
start "MomentumX Frontend" cmd /k "cd /d %ROOT%\frontend && (if not exist build yarn build) && npx serve -s build -l tcp://127.0.0.1:3000"

echo.
echo ============================================================
echo MomentumX is starting in 3 separate windows.
echo Backend:  http://127.0.0.1:8001/api
echo Frontend: http://127.0.0.1:3000
echo Access it from the VPS's own browser over RDP.
echo ============================================================
pause
