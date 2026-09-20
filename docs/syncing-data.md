# 4. Syncing data to another drive

This is for making a **backup copy** of `data/` (your files, thumbnails, and `database.db`) onto
another drive - as opposed to [external-drive.md](external-drive.md), which is about *relocating*
where SCloud actively reads/writes from.

## Why stop the container first

`database.db` is a single SQLite file. Copying it while SCloud is actively writing to it (e.g.
mid-upload) can copy it in an inconsistent state. The simplest safe approach is to briefly stop
the container, copy everything, then start it again - typically a few seconds of downtime.

If you'd rather not stop it, use SQLite's own online backup (see the "hot backup" note at the
bottom) for the database specifically, and just note that files uploaded *during* the copy might
not make it into that particular backup snapshot.

## Windows (PowerShell)

```powershell
cd scloud
docker compose stop app

# Mirror ./data onto the backup drive. /MIR keeps the backup an exact mirror
# (deletes files on the backup that no longer exist in the source) - drop
# /MIR for an additive-only copy instead.
robocopy .\data E:\scloud-backup\data /MIR /Z /R:3

docker compose start app
```

`robocopy` exit codes 0-7 mean success (it uses bit flags for "files copied" etc, not just 0/1) -
anything 8+ is a real error worth investigating.

## Linux / macOS

```bash
cd scloud
docker compose stop app

rsync -av --delete ./data/ /mnt/backup-drive/scloud-data/

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
src = sqlite3.connect('/app/data/database.db')
dst = sqlite3.connect('/app/data/database.backup.db')
src.backup(dst)
dst.close()
src.close()
"
```

This uses SQLite's own consistent online backup API, so it's always a clean snapshot even while
the app is running. Copy `data/database.backup.db` off to your backup location afterward. This
only covers the database (tags, file metadata, sharing/group structure) - you'd still want to
`rsync`/`robocopy` the actual file/thumbnail folders separately (those are just static files once
uploaded, so copying them without stopping the container is safe).
