# 2. Linux setup (Docker)

## Prerequisites

- **Docker Engine + Compose plugin.** Official install guide (works for Ubuntu/Debian/Fedora/etc.):
  https://docs.docker.com/engine/install/
  After installing, add yourself to the `docker` group so you don't need `sudo` for every command:
  ```bash
  sudo usermod -aG docker $USER
  # then log out and back in (or `newgrp docker`)
  ```
- **Git** - `sudo apt install git` (Debian/Ubuntu) or your distro's equivalent.

## First-time setup

```bash
git clone https://github.com/dwarakhnv/scloud.git
cd scloud
chmod +x launch.sh
./launch.sh
```

`launch.sh` does everything for you:

1. Pulls the latest code (harmless on a fresh clone).
2. Creates `.env` from `.env.example` if you don't have one yet.
3. Builds the Docker image.
4. Starts the container, which on its own first boot:
   - Creates `config/config.env` from the template and generates a random secret key.
   - Runs database migrations (creates `data/database.db` if it doesn't exist).
5. Prints the URL to open (default http://localhost:5125).

Create your admin account (one-time):

```bash
docker compose exec app python manage.py createsuperuser
```

Then open http://localhost:5125 and sign in. If SCloud is running on a headless server, use that
machine's LAN IP instead of `localhost` (e.g. `http://192.168.1.50:5125`), and set
`ALLOWED_HOSTS` in `config/config.env` to include that IP or hostname.

## Everyday use

- **Start it up again later:** `docker compose up -d`, or re-run `./launch.sh` (also pulls updates).
- **Stop it:** `docker compose down`
- **View logs:** `docker compose logs -f app`
- **Update to the latest version:** `./launch.sh`
- **Run it as a system service** so it starts on boot: `docker compose` already sets
  `restart: unless-stopped` on the container, so as long as the Docker daemon starts on boot
  (`sudo systemctl enable docker`), SCloud comes back up automatically after a reboot.

## Where your files live by default

Right inside the cloned folder:

```
scloud/
  data/      <- photos, videos, thumbnails, database.db
  config/    <- config.env
```

If you want this on a separate disk/mount (recommended for anything beyond quick testing - see
[external-drive.md](external-drive.md)), you only need to edit `.env`, not anything above.

## Exposing it publicly with a Cloudflare Tunnel

SCloud always listens on `SCLOUD_PORT` (5125 by default) on the machine it's running on. To make
it reachable from the internet without opening a port on your router, point `cloudflared` at that
same local port:

```bash
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
itself doesn't need to run inside Docker - it just needs network access to `localhost:5125` on the
same machine, so running it directly on the host (or as its own separate container on the same
Docker network) both work.

## Common gotchas

- **Permission denied running `docker` commands** - you weren't added to the `docker` group, or
  haven't re-logged-in since being added. Use `sudo` as a workaround, or fix the group membership.
- **Port 5125 already in use** - edit `.env`, change `SCLOUD_PORT=5125` to something else, then
  `docker compose up -d` again.
- **Firewall blocking access from other devices on your network** - open the port you chose, e.g.
  `sudo ufw allow 5125/tcp` on Ubuntu.
