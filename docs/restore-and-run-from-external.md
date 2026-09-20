# 5. Restoring data, or running SCloud directly from an external drive

Two related scenarios:

- **Restore**: copy a `data/` backup *back onto* a machine's local disk.
- **Run from external**: skip copying entirely and point SCloud straight at a `data/` folder that
  already lives on an external/portable drive (e.g. one you carry between a desktop and a laptop).

Both rely on the same mechanism as [external-drive.md](external-drive.md): `.env`'s
`SCLOUD_DATA_DIR` decides where the container reads/writes data. `config/config.env`'s
`DATA_ROOT` stays `../data` in every case - never touch that for this.

## Restoring a backup to local disk

1. Make sure SCloud isn't running: `docker compose down`
2. Copy the backup into place.
   - **Windows:**
     ```powershell
     robocopy E:\scloud-backup\data .\data /MIR /Z /R:3
     ```
   - **Linux/macOS:**
     ```bash
     rsync -av --delete /mnt/backup-drive/scloud-data/ ./data/
     ```
3. Make sure `.env` points at the local folder (the default): `SCLOUD_DATA_DIR=./data`
4. Start it up: `docker compose up -d`

Your users, groups, tags, and files come back exactly as they were at backup time - nothing else
to configure, since it's the same `database.db` plus the same file layout.

## Running SCloud directly from an external/portable drive

Useful if you want to plug a drive into whichever machine you're at and just run SCloud there,
without maintaining a separate local copy.

### One-time: get the drive into the right shape

If the drive doesn't already have SCloud data on it, create the layout once:

```bash
mkdir -p /path/to/drive/scloud-data
```

(Windows: `New-Item -ItemType Directory -Path E:\scloud-data`)

If it already has a `data/` folder from a previous SCloud install (see "Restoring" above, just
point the copy destination at the drive instead of `./data`), you're already set.

### Every time you plug it in and want to use it

1. Clone/keep the SCloud **code** on the machine you're using (the drive only needs to hold the
   `data/` folder, not the git checkout - re-cloning code is free and fast; your actual media
   isn't).
   ```bash
   git clone https://github.com/dwarakhnv/scloud.git
   cd scloud
   ```
2. Copy `.env.example` to `.env` if you haven't already, and point it at the drive:
   ```
   SCLOUD_DATA_DIR=/path/to/drive/scloud-data
   ```
   (Windows: `SCLOUD_DATA_DIR=E:/scloud-data`, and remember to share that drive with Docker
   Desktop first - see [external-drive.md](external-drive.md#windows).)
3. `./launch.sh` (or `.\launch.ps1` on Windows) - builds the image locally and starts the
   container against the drive's data.
4. When you're done, `docker compose down` and it's safe to unplug the drive.

### Moving the drive to a different machine

Exactly the same steps as above, on the new machine - clone the code fresh there too, point
`SCLOUD_DATA_DIR` at wherever the drive mounts on *that* machine (drive letters/mount paths can
differ between machines), and start it up. The `database.db` and files travel entirely on the
drive, so the new machine picks up right where the old one left off - same users, same
`SECRET_KEY` even (since `config/config.env` is per-*install*, not per-drive, you'll get a new
`SECRET_KEY` generated on a machine that's never run SCloud before; this only invalidates existing
login sessions, not your data, so just sign in again).

### A note on safely unplugging

Always `docker compose down` (or at least `docker compose stop`) before physically disconnecting
the drive. Docker/SQLite may still have the database file open otherwise, and pulling a drive out
from under an open file is how corruption happens.
