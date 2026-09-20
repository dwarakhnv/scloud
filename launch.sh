#!/usr/bin/env bash
# One command to get SCloud running (or updated) via Docker on Linux/macOS.
#
#   git clone https://github.com/dwarakhnv/scloud.git
#   cd scloud
#   ./launch.sh
#
# Safe to re-run any time: it pulls the latest code, (re)builds the image,
# and restarts the container. First-time env/database setup happens
# automatically inside the container (see docker/entrypoint.sh).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d .git ]; then
    echo "==> Pulling latest changes from git..."
    git pull --ff-only || echo "    (skipping - not on a clean fast-forward-able branch, using code as-is)"
else
    echo "==> Not a git checkout, skipping git pull."
fi

if [ ! -f .env ]; then
    echo "==> No .env found, creating one from .env.example."
    cp .env.example .env
fi

echo "==> Building the SCloud image..."
docker compose build

echo "==> Starting SCloud..."
docker compose up -d

echo ""
echo "==> Waiting for it to come up..."
sleep 3
docker compose logs --tail=40 app

PORT=$(grep -E '^SCLOUD_PORT=' .env | cut -d= -f2)
PORT=${PORT:-5125}

echo ""
echo "SCloud is running: http://localhost:${PORT}"
echo ""
echo "First time here? Create your admin account with:"
echo "  docker compose exec app python manage.py createsuperuser"
echo ""
echo "(Or set DJANGO_SUPERUSER_USERNAME/_EMAIL/_PASSWORD in .env before running"
echo " this script and one gets created automatically.)"
