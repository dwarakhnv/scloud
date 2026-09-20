# 4. Syncing data to another drive

This is for making a **backup copy** of `data/` (files/thumbnails) and `db/` (the sqlite database)
onto another drive - as opposed to [external-drive.md](external-drive.md), which is about
*relocating* where SCloud actively reads/writes from.

They're backed up a little differently, since they behave differently:

- **`data/`** is just static files once uploaded - safe to copy anytime, even while the container
  is running, no special handling needed.
- **`db/database.db`** is a single SQLite file that SCloud may be actively writing to. Copying it
  mid-write can capture it in an inconsistent state, so either stop the container briefly first,
  or use SQLite's own online backup API (see the "hot backup" section below) if you'd rather not
  take any downtime.

## Windows (PowerShell)

```powershell
cd scloud
docker compose stop app

# Mirror both folders onto the backup drive. /MIR keeps the backup an exact
# mirror (deletes files on the backup that no longer exist in the source) -
# drop /MIR for an additive-only copy instead.
robocopy .\data E:\scloud-backup\data /MIR /Z /R:3
robocopy .\db   E:\scloud-backup\db   /MIR /Z /R:3

docker compose start app
```

`robocopy` exit codes 0-7 mean success (it uses bit flags for "files copied" etc, not just 0/1) -
anything 8+ is a real error worth investigating.

## Linux / macOS

```bash
cd scloud
docker compose stop app

rsync -av --delete ./data/ /mnt/backup-drive/scloud-data/
rsync -av --delete ./db/   /mnt/backup-drive/scloud-db/

docker compose start app
```

Drop `--delete` if you want the backup to accumulate old files rather than mirror deletions too.

## Automating it

Both commands above are safe to put in a scheduled task:

- **Windows:** Task Scheduler → create a task that runs a `.ps1` script containing the block
  above, on whatever schedule you like (daily, weekly, ...).
- **Linux:** a cron job, e.g. `0 3 * * * /home/you/scloud-backup.sh` for a nightly 3am backup.

Keep the stop/copy/start sequence together in one script so the app is only down for the seconds
it takes to copy - `rsync`/`robocopy` only transfer changed data on subsequent runs, so repeat
backups after the first one are fast.

## Hot backup of just the database (optional, no downtime)

If you want a database snapshot without stopping the container at all:

```bash
docker compose exec app python -c "
import sqlite3
src = sqlite3.connect('/app/db/database.db')
dst = sqlite3.connect('/app/db/database.backup.db')
src.backup(dst)
dst.close()
src.close()
"
```

This uses SQLite's own consistent online backup API, so it's always a clean snapshot even while
the app is running. Copy `db/database.backup.db` off to your backup location afterward (it lands
in your local `SCLOUD_DB_DIR`, alongside the live `database.db`). This only covers the database
(tags, file metadata, sharing/group structure) - `data/` (the actual files/thumbnails) is safe to
`rsync`/`robocopy` separately without stopping anything, as noted above.
