$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. V2 services use local fallback until enabled."
}

Write-Host "Starting EduVault V2 backend..."
Start-Process python -ArgumentList "run_mvp.py" -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $root "v2-backend.stdout.log") `
    -RedirectStandardError (Join-Path $root "v2-backend.stderr.log")

Write-Host "Starting EduVault V2 frontend..."
Start-Process npm.cmd -ArgumentList "run","dev" -WorkingDirectory (Join-Path $root "frontend") -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $root "v2-frontend.stdout.log") `
    -RedirectStandardError (Join-Path $root "v2-frontend.stderr.log")

Write-Host ""
Write-Host "EduVault V2 demo is starting:"
Write-Host "  Frontend: http://127.0.0.1:3000"
Write-Host "  API:      http://127.0.0.1:8080/docs"
Write-Host "  Accounts: GV001, GVNEW, TBM01, ADMIN (password equals account code)"
Write-Host ""
Write-Host "For real MySQL/MinIO/Redis/Qdrant, run:"
Write-Host "  docker compose -f docker-compose.v2.yml up -d"
Write-Host "Then enable the V2 services in .env and restart this script."
