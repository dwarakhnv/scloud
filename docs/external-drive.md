# 3. Switching to an external drive

SCloud's Docker setup deliberately keeps this simple: the container always reads/writes
`/app/data` and `/app/config` internally. What those paths actually map to *on your machine* is
controlled by two lines in `.env`:

```
SCLOUD_DATA_DIR=./data
SCLOUD_CONFIG_DIR=./config
```

To move storage onto an external drive, you change `SCLOUD_DATA_DIR` to point at it and restart
the container. **No image rebuild, no code change, no editing `config/config.env`'s `DATA_ROOT`**
(leave that as `../data` - it's relative to the *container's* filesystem, not your host).

## Windows

1. Plug in the external drive. Note its drive letter, e.g. `E:`.
2. Make sure Docker Desktop can see it: **Docker Desktop → Settings → Resources → File Sharing**,
   add the `E:\` drive if it isn't listed already, then **Apply & Restart**.
3. Create a folder for SCloud's data on the drive, e.g. `E:\scloud-data`.
4. Stop SCloud: `docker compose down`
5. Edit `.env`:
   ```
   SCLOUD_DATA_DIR=E:/scloud-data
   ```
   (forward slashes work fine here even on Windows, and avoid quoting headaches).
6. Start it back up: `docker compose up -d`
7. Check it came up clean: `docker compose logs -f app`

If this is a *brand new* external drive (no existing SCloud data on it), the container will just
create a fresh `database.db` there on first start - you'll need to `createsuperuser` again. If
you're moving *existing* data over, see [syncing-data.md](syncing-data.md) first to copy it across
before switching `SCLOUD_DATA_DIR`, or [restore-and-run-from-external.md](restore-and-run-from-external.md)
if the drive already has a full SCloud data folder on it (e.g. from another machine).

## Linux

1. Mount the external drive if it isn't auto-mounted, e.g.:
   ```bash
   sudo mkdir -p /mnt/scloud-drive
   sudo mount /dev/sdX1 /mnt/scloud-drive   # replace sdX1 with your actual device
   ```
   For something you want to survive reboots, add an entry to `/etc/fstab` instead of a one-off
   `mount` command.
2. Create a folder for SCloud's data on it:
   ```bash
   mkdir -p /mnt/scloud-drive/scloud-data
   ```
3. Stop SCloud: `docker compose down`
4. Edit `.env`:
   ```
   SCLOUD_DATA_DIR=/mnt/scloud-drive/scloud-data
   ```
5. Start it back up: `docker compose up -d`
6. Check it came up clean: `docker compose logs -f app`

## Moving `config/` too (optional)

Most people leave `config/` on the local disk (it's tiny - just `config.env`) and only move
`data/`. If you want config on the external drive as well, do the same thing with
`SCLOUD_CONFIG_DIR` in `.env`. Just make sure the drive is mounted *before* Docker starts, or the
container will fail to find it.

## Verifying it worked

```bash
docker compose exec app python -c "from scloud.constants import Constants; print(Constants.DATA_ROOT)"
```

This always prints `/app/data` (the container's view) - to confirm the *host* mapping, check
`docker compose config` and look at the resolved `volumes:` section, or just look at the external
drive directly and confirm `database.db`, `user_<id>/`, etc. appear there after you upload
something.
