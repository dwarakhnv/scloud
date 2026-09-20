# 1. Windows setup (Docker)

## Prerequisites

- **Docker Desktop for Windows** - https://www.docker.com/products/docker-desktop/
  - During install, use the WSL2 backend (the installer defaults to this).
  - Launch Docker Desktop at least once and make sure it says "Engine running" before continuing.
- **Git for Windows** - https://git-scm.com/download/win
- PowerShell (built into Windows - the steps below use it).

## First-time setup

Open PowerShell and run:

```powershell
git clone https://github.com/dwarakhnv/scloud.git
cd scloud
.\launch.ps1
```

`launch.ps1` does everything for you:

1. Pulls the latest code (harmless on a fresh clone).
2. Creates `.env` from `.env.example` if you don't have one yet.
3. Builds the Docker image.
4. Starts the container, which on its own first boot:
   - Creates `config/config.env` from the template and generates a random secret key.
   - Runs database migrations (creates `data/database.db` if it doesn't exist).
5. Prints the URL to open (default http://localhost:5125).

Create your admin account (one-time):

```powershell
docker compose exec app python manage.py createsuperuser
```

Then open http://localhost:5125 and sign in.

## Everyday use

- **Start it up again later:** `docker compose up -d` (from the `scloud` folder), or just run
  `.\launch.ps1` again - it also pulls any updates first.
- **Stop it:** `docker compose down`
- **View logs:** `docker compose logs -f app`
- **Update to the latest version:** `.\launch.ps1` (pulls + rebuilds + restarts in one go).

## Where your files live by default

Right inside the cloned folder:

```
scloud\
  data\      <- photos, videos, thumbnails, database.db
  config\    <- config.env
```

If you want this on a different drive (recommended once you have real data - see
[external-drive.md](external-drive.md)), you only need to edit `.env`, not anything above.

## Exposing it publicly with a Cloudflare Tunnel

SCloud always listens on `SCLOUD_PORT` (5125 by default) on the machine it's running on. To make
it reachable from the internet without opening a port on your router, install
[`cloudflared`](https://github.com/cloudflare/cloudflared/releases) and point it at that same
local port:

```powershell
# One-time: authenticate and create a tunnel (see Cloudflare's docs for the
# full walkthrough - https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
cloudflared tunnel login
cloudflared tunnel create scloud

# Route your domain/subdomain to it
cloudflared tunnel route dns scloud photos.example.com

# Run it, pointed at SCloud's local port
cloudflared tunnel run --url http://localhost:5125 scloud
```

If you changed `SCLOUD_PORT` in `.env`, use that port number here instead of 5125. `cloudflared`
doesn't need to run inside Docker - it just needs network access to `localhost:5125` on the same
machine, so running it as a normal Windows program alongside Docker Desktop works fine.

## Common gotchas

- **"docker: command not found" / docker not recognized** - Docker Desktop isn't running, or you
  need to restart your terminal after installing it.
- **Port 5125 already in use** - edit `.env`, change `SCLOUD_PORT=5125` to something else (e.g.
  `8080`), then `docker compose up -d` again.
- **Sharing a drive other than C: with Docker Desktop** - if you point `SCLOUD_DATA_DIR` at, say,
  `D:\scloud-data`, Docker Desktop needs permission to share that drive: Docker Desktop → Settings
  → Resources → File Sharing, add the drive, then Apply & Restart. See
  [external-drive.md](external-drive.md) for the full walkthrough.
