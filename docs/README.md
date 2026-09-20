# SCloud docs

Everything here assumes you're running SCloud via Docker (see the root
[README.md](../README.md) for a non-Docker/bare-metal setup, which still
works but isn't what these guides cover).

- [1. Windows setup](windows-setup.md)
- [2. Linux setup](linux-setup.md)
- [3. Switching to an external drive](external-drive.md)
- [4. Syncing data to another drive](syncing-data.md)
- [5. Restoring data, or running SCloud directly from an external drive](restore-and-run-from-external.md)

## The short version

Everywhere below boils down to the same four pieces:

1. **The code** - a git checkout of https://github.com/dwarakhnv/scloud.git, built into a Docker
   image by `docker-compose.yml`.
2. **`config/`** - `config.env` (settings). Auto-created from `config.env.example` the first time
   the container starts.
3. **`data/`** - your actual files and thumbnails.
4. **`db/`** - the sqlite database (users, tags, file metadata, group/sharing structure).

`data/` and `db/` are deliberately **separate** directories, mounted as separate volumes. `data/`
is safe to put on a portable drive you move between machines (even between Windows and Linux -
format it exFAT); `db/` should always stay on local, native storage, since SQLite needs reliable
file locking that removable/cross-platform drives don't provide. See
[external-drive.md](external-drive.md) for the full reasoning.

Where `data/`, `db/`, and `config/` physically live on disk is controlled entirely by three lines
in your `.env` file (`SCLOUD_DATA_DIR`, `SCLOUD_DB_DIR`, `SCLOUD_CONFIG_DIR`), which get mounted
into the container as volumes. Moving storage to another disk is just changing those paths and
restarting the container - never a code change, never a rebuild.
