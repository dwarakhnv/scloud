"""Best-effort extraction of "when was this actually taken" from a media
file, used for the "media create date" sort option. Falls back to None
(callers then sort by upload date instead)."""
import logging
from datetime import datetime

from django.utils import timezone

logger = logging.getLogger("scloud.media_metadata")

_EXIF_DATE_TAGS = (36867, 36868, 306)  # DateTimeOriginal, DateTimeDigitized, DateTime


def extract_captured_at(path, is_image: bool):
    if not is_image:
        return None
    try:
        from PIL import Image
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            for tag in _EXIF_DATE_TAGS:
                value = exif.get(tag)
                if value:
                    naive = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                    return timezone.make_aware(naive, timezone.get_default_timezone())
    except Exception:
        logger.debug("Could not read EXIF date from %s", path, exc_info=True)
    return None
