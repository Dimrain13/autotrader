<#
Uninstalls the MomentumX Windows services created by install_nssm_service.ps1.
Run as Administrator.
#>
param([string]$NssmPath = "nssm.exe")

& $NssmPath stop MomentumXBackend
& $NssmPath stop MomentumXFrontend
& $NssmPath remove MomentumXBackend confirm
& $NssmPath remove MomentumXFrontend confirm

Write-Host "MomentumX services removed." -ForegroundColor Green
