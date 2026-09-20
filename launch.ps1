# One command to get SCloud running (or updated) via Docker on Windows.
#
#   git clone https://github.com/dwarakhnv/scloud.git
#   cd scloud
#   .\launch.ps1
#
# Safe to re-run any time: it pulls the latest code, (re)builds the image,
# and restarts the container. First-time env/database setup happens
# automatically inside the container (see docker/entrypoint.sh).

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path ".git") {
    Write-Host "==> Pulling latest changes from git..."
    try {
        git pull --ff-only
    } catch {
        Write-Host "    (skipping - not on a clean fast-forward-able branch, using code as-is)"
    }
} else {
    Write-Host "==> Not a git checkout, skipping git pull."
}

if (-not (Test-Path ".env")) {
    Write-Host "==> No .env found, creating one from .env.example."
    Copy-Item ".env.example" ".env"
}

Write-Host "==> Building the SCloud image..."
docker compose build

Write-Host "==> Starting SCloud..."
docker compose up -d

Write-Host ""
Write-Host "==> Waiting for it to come up..."
Start-Sleep -Seconds 3
docker compose logs --tail=40 app

$port = "5125"
if (Test-Path ".env") {
    $line = Select-String -Path ".env" -Pattern "^SCLOUD_PORT=" -ErrorAction SilentlyContinue
    if ($line) { $port = ($line.Line -split "=")[1].Trim() }
}

Write-Host ""
Write-Host "SCloud is running: http://localhost:$port"
Write-Host ""
Write-Host "First time here? Create your admin account with:"
Write-Host "  docker compose exec app python manage.py createsuperuser"
Write-Host ""
Write-Host "(Or set DJANGO_SUPERUSER_USERNAME/_EMAIL/_PASSWORD in .env before running"
Write-Host " this script and one gets created automatically.)"
