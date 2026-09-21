"""
Central place for all static, environment-driven configuration.

Everything here is derived from ``config/config.env`` (one level above the
``src`` directory) so that data/thumbnail/database locations can be moved
(e.g. to an external drive) without touching any code.

Note that DATA_ROOT (files/thumbnails) and DATABASE_PATH (the sqlite file)
are independent settings on purpose - see the comment on DATABASE_PATH
below for why the database shouldn't live on the same portable drive as
your media.
"""
import os
from pathlib import Path

from dotenv import dotenv_values

# src/scloud/constants.py -> src/scloud -> src -> <project root>
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "config.env"

_env = {}
if CONFIG_FILE.exists():
    _env = dotenv_values(CONFIG_FILE)


def _get(key, default=None):
    # Environment variables take precedence over the config file, which in
    # turn takes precedence over the hardcoded default.
    return os.environ.get(key, _env.get(key, default))


def _resolve_path(value, default_rel):
    """Resolve a path from config.env relative to the config directory."""
    raw = value or default_rel
    p = Path(raw)
    if not p.is_absolute():
        p = (CONFIG_DIR / p).resolve()
    return p


class Constants:
    """Static configuration for the whole project. Import and use directly:

        from scloud.constants import Constants
        Constants.DATA_ROOT
    """

    # --- Core paths -------------------------------------------------
    PROJECT_ROOT = PROJECT_ROOT
    CONFIG_FILE = CONFIG_FILE

    # DATA_ROOT holds files/thumbnails and is safe to put on a portable,
    # cross-platform-formatted drive (e.g. exFAT) that moves between Windows
    # and Linux machines - these are whole-file, mostly-write-once blobs.
    #
    # DATABASE_PATH is intentionally a SEPARATE setting, defaulting to a
    # different directory ("../db" rather than "../data"). SQLite relies on
    # real file locking to stay consistent, which is exactly what's flaky or
    # missing on removable media and cross-platform filesystems (exFAT has no
    # POSIX locking at all; NTFS-via-ntfs-3g and other FUSE drivers are
    # unreliable for it too). Keep the database on the local, native
    # filesystem of whichever machine is actually running the app.
    DATA_ROOT = _resolve_path(_get("DATA_ROOT"), "../data")
    DATABASE_PATH = _resolve_path(_get("DATABASE_PATH"), "../db/database.db")

    # --- Django settings sourced from config ------------------------
    SECRET_KEY = _get("SECRET_KEY", "insecure-dev-key-change-me")
    DEBUG = str(_get("DEBUG", "True")).strip().lower() in ("1", "true", "yes", "on")
    ALLOWED_HOSTS = [h.strip() for h in str(_get("ALLOWED_HOSTS", "*")).split(",") if h.strip()]

    # Django 4+ checks the Origin header on unsafe (POST/PUT/...) requests
    # against this list, SEPARATELY from ALLOWED_HOSTS - a wildcard
    # ALLOWED_HOSTS does NOT cover this. Anyone serving the site on a real
    # domain (directly, behind nginx, or through a tunnel like cloudflared)
    # must list it here, scheme included, e.g.
    # CSRF_TRUSTED_ORIGINS=https://aeoncloud.online,https://www.aeoncloud.online
    # Leaving this unset is exactly what causes "CSRF verification failed"
    # on login for anyone reachable via a domain rather than bare localhost.
    CSRF_TRUSTED_ORIGINS = [
        o.strip() for o in str(_get("CSRF_TRUSTED_ORIGINS", "")).split(",") if o.strip()
    ]

    # Set to True (the default) when running behind a reverse proxy or
    # tunnel that terminates TLS and forwards plain HTTP to this container
    # (nginx, Cloudflare Tunnel, etc.) - tells Django to trust the
    # X-Forwarded-Proto header so it knows the original request was HTTPS.
    # Only disable this if the app is reachable directly with no proxy in
    # front of it at all.
    BEHIND_PROXY = str(_get("BEHIND_PROXY", "True")).strip().lower() in ("1", "true", "yes", "on")
    MAX_UPLOAD_SIZE_MB = int(_get("MAX_UPLOAD_SIZE_MB", 10240))  # 10 GB default
    MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

    # Large uploads are sent from the browser in chunks so a flaky mobile
    # connection only has to retry a small piece, not the whole file.
    UPLOAD_CHUNK_SIZE_MB = int(_get("UPLOAD_CHUNK_SIZE_MB", 8))
    UPLOAD_CHUNK_SIZE_BYTES = UPLOAD_CHUNK_SIZE_MB * 1024 * 1024

    # --- Naming conventions for on-disk storage ----------------------
    USER_PREFIX = "user_"
    GROUP_PREFIX = "group_"
    FILES_SUBDIR = "files"
    THUMBNAILS_SUBDIR = "thumbnails"
    UPLOAD_TMP_SUBDIR = "_uploads_tmp"

    THUMBNAIL_MAX_DIMENSION = int(_get("THUMBNAIL_SIZE", 256))  # px, long edge
    THUMBNAIL_JPEG_QUALITY = 60

    IMAGE_EXTENSIONS = {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tiff", ".tif",
    }
    VIDEO_EXTENSIONS = {
        ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp", ".wmv", ".mpg", ".mpeg",
    }

    # --- Outgoing email (used for password reset links) ---------------
    EMAIL_HOST = _get("EMAIL_HOST", "")
    EMAIL_PORT = int(_get("EMAIL_PORT", 587))
    EMAIL_HOST_USER = _get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = _get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = str(_get("EMAIL_USE_TLS", "True")).strip().lower() in ("1", "true", "yes", "on")
    DEFAULT_FROM_EMAIL = _get("DEFAULT_FROM_EMAIL", "SCloud <noreply@scloud.local>")

    @classmethod
    def ensure_dirs(cls):
        cls.DATA_ROOT.mkdir(parents=True, exist_ok=True)
        cls.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.upload_tmp_dir().mkdir(parents=True, exist_ok=True)

    @classmethod
    def upload_tmp_dir(cls) -> Path:
        # Lives on the same drive as DATA_ROOT (which may be an external
        # drive) so assembling a multi-GB chunked upload never needs a
        # slow cross-drive move, and never fills up the OS system drive.
        return cls.DATA_ROOT / cls.UPLOAD_TMP_SUBDIR

    # --- Owner-scoped directory helpers -------------------------------
    @classmethod
    def owner_root(cls, owner_type: str, owner_id: int) -> Path:
        """owner_type is 'user' or 'group'."""
        prefix = cls.USER_PREFIX if owner_type == "user" else cls.GROUP_PREFIX
        return cls.DATA_ROOT / f"{prefix}{owner_id}"

    @classmethod
    def files_dir(cls, owner_type: str, owner_id: int) -> Path:
        d = cls.owner_root(owner_type, owner_id) / cls.FILES_SUBDIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def thumbnails_dir(cls, owner_type: str, owner_id: int) -> Path:
        d = cls.owner_root(owner_type, owner_id) / cls.THUMBNAILS_SUBDIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def is_image(cls, filename: str) -> bool:
        return Path(filename).suffix.lower() in cls.IMAGE_EXTENSIONS

    @classmethod
    def is_video(cls, filename: str) -> bool:
        return Path(filename).suffix.lower() in cls.VIDEO_EXTENSIONS
