<#
MomentumX - Register backend (and optionally frontend) as Windows services
using NSSM (Non-Sucking Service Manager), so they survive reboots and
RDP logouts without needing a script running in an open session.

PREREQUISITES:
  1. Python 3.11+ installed, venv created + requirements installed:
       cd backend
       python -m venv venv
       venv\Scripts\activate
       pip install -r requirements.txt
  2. Node.js LTS + yarn installed, frontend built:
       cd frontend
       yarn install
       yarn build
  3. NSSM downloaded and nssm.exe available on PATH (or set $NssmPath below).
       https://nssm.cc/download
  4. MongoDB Community installed as a Windows service (its own installer
     offers "Install as a Service" - tick that box), or run separately.
  5. backend\.env configured (copy from .env.example) with a real
     JWT_SECRET, ADMIN_EMAIL/ADMIN_PASSWORD, and your Alpaca paper keys.

USAGE (run as Administrator in PowerShell):
  cd deploy\windows
  .\install_nssm_service.ps1
#>

param(
    [string]$NssmPath = "nssm.exe",
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
)

$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$VenvUvicorn = Join-Path $BackendDir "venv\Scripts\uvicorn.exe"

Write-Host "=== MomentumX Windows Service Installer ===" -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"

if (-not (Test-Path $VenvUvicorn)) {
    Write-Error "Could not find $VenvUvicorn - create the venv and pip install -r requirements.txt first."
    exit 1
}

# ---- Backend service: MomentumXBackend ----
# Bound to 127.0.0.1 only (Phase 5 network model: RDP-only, no internet exposure).
Write-Host "`nInstalling MomentumXBackend service..." -ForegroundColor Yellow
& $NssmPath install MomentumXBackend $VenvUvicorn "server:app --host 127.0.0.1 --port 8001 --workers 1"
& $NssmPath set MomentumXBackend AppDirectory $BackendDir
& $NssmPath set MomentumXBackend DisplayName "MomentumX Trading Backend"
& $NssmPath set MomentumXBackend Description "FastAPI backend for MomentumX (Alpaca paper/live trading)"
& $NssmPath set MomentumXBackend Start SERVICE_AUTO_START
& $NssmPath set MomentumXBackend AppStdout (Join-Path $BackendDir "service_stdout.log")
& $NssmPath set MomentumXBackend AppStderr (Join-Path $BackendDir "service_stderr.log")
& $NssmPath set MomentumXBackend AppRotateFiles 1

# ---- Frontend service: MomentumXFrontend ----
# Serves the pre-built React app. Rebuild with `yarn build` after any frontend change.
$ServeCmd = "npx.cmd"
Write-Host "`nInstalling MomentumXFrontend service..." -ForegroundColor Yellow
& $NssmPath install MomentumXFrontend $ServeCmd "serve -s build -l tcp://127.0.0.1:3000"
& $NssmPath set MomentumXFrontend AppDirectory $FrontendDir
& $NssmPath set MomentumXFrontend DisplayName "MomentumX Trading Frontend"
& $NssmPath set MomentumXFrontend Description "Static server for the built MomentumX React app"
& $NssmPath set MomentumXFrontend Start SERVICE_AUTO_START
& $NssmPath set MomentumXFrontend AppStdout (Join-Path $FrontendDir "service_stdout.log")
& $NssmPath set MomentumXFrontend AppStderr (Join-Path $FrontendDir "service_stderr.log")

Write-Host "`nStarting services..." -ForegroundColor Yellow
& $NssmPath start MomentumXBackend
& $NssmPath start MomentumXFrontend

Write-Host "`n=== Done ===" -ForegroundColor Green
Write-Host "Backend:  http://127.0.0.1:8001/api"
Write-Host "Frontend: http://127.0.0.1:3000"
Write-Host "Manage services with: services.msc, or 'nssm stop/start/remove MomentumXBackend'"
