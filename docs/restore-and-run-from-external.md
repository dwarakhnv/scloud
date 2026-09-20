# 5. Restoring data, or running SCloud directly from an external drive

Two related scenarios:

- **Restore**: copy a backup *back onto* a machine's local disk.
- **Run from external**: point SCloud's file storage straight at a drive that already has
  `data/` on it (e.g. a drive you carry between a desktop and a laptop), instead of copying
  everything onto each machine's local disk first.

Both rely on the same mechanism as [external-drive.md](external-drive.md): `.env`'s
`SCLOUD_DATA_DIR` decides where the container reads/writes files, and `SCLOUD_DB_DIR` decides
where it reads/writes the database. **Read that page first if you haven't** - the short version is
that the database deliberately does *not* live on the portable drive alongside your media, so it
needs a small extra step whenever you move to a different machine (see below).

## Restoring a backup to local disk

1. Make sure SCloud isn't running: `docker compose down`
2. Copy both backups into place.
   - **Windows:**
     ```powershell
     robocopy E:\scloud-backup\data .\data /MIR /Z /R:3
     robocopy E:\scloud-backup\db   .\db   /MIR /Z /R:3
     ```
   - **Linux/macOS:**
     ```bash
     rsync -av --delete /mnt/backup-drive/scloud-data/ ./data/
     rsync -av --delete /mnt/backup-drive/scloud-db/   ./db/
     ```
3. Make sure `.env` points at the local folders (the default):
   ```
   SCLOUD_DATA_DIR=./data
   SCLOUD_DB_DIR=./db
   ```
4. Start it up: `docker compose up -d`

Your users, groups, tags, and files come back exactly as they were at backup time.

## Running SCloud's file storage directly from a portable drive

Useful if you want to plug a drive of photos/videos into whichever machine you're at, without
copying that (potentially huge) media library onto each machine's local disk first.

**Important:** the database is what actually knows which files exist, who owns them, their tags,
group membership, etc. - the files on the drive are meaningless to a fresh, empty database. So
"running from the drive" really means: **files come from the drive, but you still need a matching
database on each machine's local disk.** The database itself is small (a few MB even with
thousands of files, since it only holds metadata, not the media), so this is a quick copy each
time you switch machines - not a real chore.

### One-time: get the drive into the right shape

Format it exFAT if it'll move between Windows and Linux (see
[external-drive.md](external-drive.md#moving-a-drive-between-windows-and-linux)), then create a
folder for SCloud's files on it:

```bash
mkdir -p /path/to/drive/scloud-data
```

(Windows: `New-Item -ItemType Directory -Path E:\scloud-data`)

If it already has a `data/` folder from a previous SCloud install, you're already set - just note
where it is.

Also keep a **database backup on the drive** (as an inert file, not something SCloud reads
in-place from there) so it travels with the media:

```bash
cp db/database.db /path/to/drive/scloud-db-backup.db
```

Update this file (re-copy it) whenever you've made changes you want to bring to the next machine.

### Every time you plug it in and want to use it on a (possibly new) machine

1. Clone/keep the SCloud **code** on the machine you're using:
   ```bash
   git clone https://github.com/dwarakhnv/scloud.git
   cd scloud
   ```
2. Copy the database backup off the drive into this machine's local `db/` folder:
   ```bash
   mkdir -p db
   cp /path/to/drive/scloud-db-backup.db db/database.db
   ```
   (First time ever on this machine and don't have a backup yet? Skip this - a fresh database
   gets created automatically, you just won't see the drive's existing files listed until you
   bring a matching database over.)
3. Copy `.env.example` to `.env` if you haven't already, and point `SCLOUD_DATA_DIR` at the drive
   (leave `SCLOUD_DB_DIR` as the local default `./db`):
   ```
   SCLOUD_DATA_DIR=/path/to/drive/scloud-data
   SCLOUD_DB_DIR=./db
   ```
   (Windows: `SCLOUD_DATA_DIR=E:/scloud-data`, and remember to share that drive with Docker
   Desktop first - see [external-drive.md](external-drive.md#windows).)
4. `./launch.sh` (or `.\launch.ps1` on Windows) - builds the image locally and starts the
   container against the drive's files and this machine's local database copy.
5. Before you're done, update the backup on the drive with anything new
   (`cp db/database.db /path/to/drive/scloud-db-backup.db`), then `docker compose down` and it's
   safe to unplug.

### Moving to a different machine

Same steps as above on the new machine - clone the code fresh there too, copy the database backup
off the drive into that machine's local `db/`, point `SCLOUD_DATA_DIR` at wherever the drive mounts
there (drive letters/mount paths can differ between machines), and start it up.

### A note on safely unplugging

Always `docker compose down` (or at least `docker compose stop`) before physically disconnecting
the drive - Docker may still have files on it open otherwise. Since the database itself now never
lives on the portable drive, you've already removed the highest-risk failure mode (a corrupted
SQLite file from an improper unplug); this is just good hygiene for the files themselves.
