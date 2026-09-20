# 3. Switching to an external drive

SCloud's Docker setup deliberately keeps this simple: the container always reads/writes
`/app/data`, `/app/db`, and `/app/config` internally. What those paths actually map to *on your
machine* is controlled by three lines in `.env`:

```
SCLOUD_DATA_DIR=./data
SCLOUD_DB_DIR=./db
SCLOUD_CONFIG_DIR=./config
```

**These are separate on purpose.** `SCLOUD_DATA_DIR` (files + thumbnails) is safe to put on a
portable drive, including one you move between Windows and Linux. `SCLOUD_DB_DIR` (the sqlite
database) should stay on **local, native storage** on whichever machine is actually running
SCloud - never the portable drive. See "Why the database stays local" below for the reasoning.

To move file storage onto an external drive, you change `SCLOUD_DATA_DIR` to point at it and
restart the container. **No image rebuild, no code change, and no editing `config/config.env`'s
`DATA_ROOT`/`DATABASE_PATH`** - those stay `../data` and `../db` respectively, since they're
relative to the *container's* filesystem, not your host.

## Why the database stays local

SQLite relies on real, reliable file locking to avoid corrupting itself when the app reads and
writes it. That's exactly what's missing or unreliable on the filesystems you'd use for a
drive that needs to work on both Windows and Linux:

- **exFAT** (the standard cross-platform choice) has no POSIX file locking at all.
- **NTFS** read/written from Linux goes through the `ntfs-3g` FUSE driver, whose locking/POSIX
  emulation isn't something to trust for a live database.
- Unplugging a drive - which is the whole point of a portable drive - while a database file on it
  is open is a very easy way to corrupt it.

Photos and videos don't have this problem: once uploaded, they're static, whole files. Copying,
moving, or even briefly losing access to the drive they're on doesn't corrupt a JPEG the way it
can corrupt a SQLite file mid-write. That's why `SCLOUD_DATA_DIR` and `SCLOUD_DB_DIR` are split -
put the drive-portability risk only where it's actually safe to take it.

## Windows

1. Plug in the external drive. Note its drive letter, e.g. `E:`.
2. Make sure Docker Desktop can see it: **Docker Desktop → Settings → Resources → File Sharing**,
   add the `E:\` drive if it isn't listed already, then **Apply & Restart**.
3. Create a folder for SCloud's files on the drive, e.g. `E:\scloud-data`.
4. Stop SCloud: `docker compose down`
5. Edit `.env` - only `SCLOUD_DATA_DIR` changes, leave `SCLOUD_DB_DIR` pointing at local storage:
   ```
   SCLOUD_DATA_DIR=E:/scloud-data
   SCLOUD_DB_DIR=./db
   ```
   (forward slashes work fine here even on Windows, and avoid quoting headaches).
6. Start it back up: `docker compose up -d`
7. Check it came up clean: `docker compose logs -f app`

If this is a *brand new* external drive (no existing SCloud files on it), the container will just
start writing fresh uploads there. If you're moving *existing* files over, see
[syncing-data.md](syncing-data.md) first to copy them across before switching `SCLOUD_DATA_DIR`, or
[restore-and-run-from-external.md](restore-and-run-from-external.md) if the drive already has a
full SCloud `data/` folder on it (e.g. from another machine).

## Linux

1. Mount the external drive if it isn't auto-mounted, e.g.:
   ```bash
   sudo mkdir -p /mnt/scloud-drive
   sudo mount /dev/sdX1 /mnt/scloud-drive   # replace sdX1 with your actual device
   ```
   For something you want to survive reboots, add an entry to `/etc/fstab` instead of a one-off
   `mount` command.
2. Create a folder for SCloud's files on it:
   ```bash
   mkdir -p /mnt/scloud-drive/scloud-data
   ```
3. Stop SCloud: `docker compose down`
4. Edit `.env` - only `SCLOUD_DATA_DIR` changes:
   ```
   SCLOUD_DATA_DIR=/mnt/scloud-drive/scloud-data
   SCLOUD_DB_DIR=./db
   ```
5. Start it back up: `docker compose up -d`
6. Check it came up clean: `docker compose logs -f app`

## Moving a drive between Windows and Linux

Since `SCLOUD_DATA_DIR` now only ever holds files/thumbnails (never the database - see above),
you're free to format the drive **exFAT**, which both Windows and Linux read/write natively with
no extra drivers and no ownership/permission quirks. This is the recommended format if the same
physical drive needs to plug into both OSes.

**Windows:** Right-click the drive in File Explorer → Format → File system: `exFAT`.

**Linux:**
```bash
lsblk -f                              # find the device, e.g. /dev/sdX1
sudo apt install exfatprogs           # if not already installed
sudo mkfs.exfat -n scloud-data /dev/sdX1   # DESTROYS existing data on the partition
```

If the drive already has files on it you need to keep before reformatting, back them up first
(from whichever OS it's currently readable on) with a plain file copy - since they're just static
files, an ordinary copy is all you need, no special tooling.

Once formatted exFAT, mount it and point `SCLOUD_DATA_DIR` at it exactly as in the Windows/Linux
sections above. `SCLOUD_DB_DIR` never needs to move - each machine keeps its own local database
even if they're sharing the same drive of media at different times. (If you actually want the
*same* database available on multiple machines rather than each having its own, that's a different
problem - either run SCloud on one machine and access it from others over the network, or restore
a copied `db/database.db` onto the new machine as in
[restore-and-run-from-external.md](restore-and-run-from-external.md).)

No `chown`/permission juggling needed either way - the SCloud container runs as root internally,
so it can write to the mount regardless of who owns it on the host.

## Moving `config/` too (optional)

Most people leave `config/` on the local disk (it's tiny - just `config.env`) and only move
`data/`. If you want config on the external drive as well, do the same thing with
`SCLOUD_CONFIG_DIR` in `.env`. Just make sure the drive is mounted *before* Docker starts, or the
container will fail to find it.

## Verifying it worked

```bash
docker compose exec app python -c "from scloud.constants import Constants; print(Constants.DATA_ROOT); print(Constants.DATABASE_PATH)"
```

This always prints `/app/data` and `/app/db/database.db` (the container's view) - to confirm the
*host* mapping, check `docker compose config` and look at the resolved `volumes:` section, or just
look at the external drive directly and confirm `user_<id>/`, `group_<id>/`, etc. appear there
after you upload something (and confirm `database.db` does **not** appear there - it should only
ever be in your local `SCLOUD_DB_DIR`).
