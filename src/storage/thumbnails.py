"""
Background thumbnail generation.

Thumbnail creation runs on a small shared thread pool so that upload requests
return immediately after the original file is saved, instead of blocking on
image/video processing. This is what lets the server keep handling other
requests (uploads, browsing, etc.) concurrently.
"""
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageOps

from scloud.constants import Constants

logger = logging.getLogger("scloud.thumbnails")

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumbgen")

try:
    import imageio_ffmpeg

    _FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:  # pragma: no cover - optional dependency issue
    _FFMPEG_BIN = None


def queue_thumbnail(media_file_id: int):
    """Schedule thumbnail generation for a MediaFile without blocking the caller."""
    _executor.submit(_generate_thumbnail_safe, media_file_id)


def _generate_thumbnail_safe(media_file_id: int):
    # Imported lazily to avoid app-loading issues when this module is
    # imported before Django apps are ready.
    from storage.models import MediaFile

    try:
        media_file = MediaFile.objects.get(id=media_file_id)
    except MediaFile.DoesNotExist:
        return

    try:
        thumb_name = _generate_thumbnail(media_file)
        if thumb_name:
            media_file.thumbnail_filename = thumb_name
            media_file.thumbnail_status = "ready"
        else:
            media_file.thumbnail_status = "none"
    except Exception:
        logger.exception("Thumbnail generation failed for MediaFile %s", media_file_id)
        media_file.thumbnail_status = "failed"

    media_file.save(update_fields=["thumbnail_filename", "thumbnail_status"])


def _generate_thumbnail(media_file) -> str:
    src_path = media_file.disk_path()
    thumbs_dir = Constants.thumbnails_dir(media_file.owner_type(), media_file.owner_id_value())
    thumb_name = f"{media_file.id}.jpg"
    thumb_path = thumbs_dir / thumb_name

    if media_file.is_image:
        _make_image_thumbnail(src_path, thumb_path)
        return thumb_name

    if media_file.is_video:
        if _FFMPEG_BIN is None:
            return ""
        ok = _make_video_thumbnail(src_path, thumb_path)
        return thumb_name if ok else ""

    return ""


def _make_image_thumbnail(src_path, thumb_path):
    with Image.open(src_path) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail(
            (Constants.THUMBNAIL_MAX_DIMENSION, Constants.THUMBNAIL_MAX_DIMENSION),
            Image.LANCZOS,
        )
        img.save(thumb_path, "JPEG", quality=Constants.THUMBNAIL_JPEG_QUALITY)


def _make_video_thumbnail(src_path, thumb_path) -> bool:
    # Grab a single frame ~1s in, downscale it, and let Pillow re-compress it
    # so the output matches the same low-quality JPEG thumbnail convention.
    raw_frame = thumb_path.with_suffix(".raw.jpg")
    cmd = [
        _FFMPEG_BIN,
        "-y",
        "-ss", "00:00:01",
        "-i", str(src_path),
        "-frames:v", "1",
        "-vf", f"scale='min({Constants.THUMBNAIL_MAX_DIMENSION},iw)':'-1'",
        str(raw_frame),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not raw_frame.exists():
        # Retry from the first frame in case the video is shorter than 1s.
        cmd[3] = "00:00:00"
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0 or not raw_frame.exists():
            return False

    try:
        with Image.open(raw_frame) as img:
            img = img.convert("RGB")
            img.save(thumb_path, "JPEG", quality=Constants.THUMBNAIL_JPEG_QUALITY)
    finally:
        raw_frame.unlink(missing_ok=True)

    return True
