"""Per-user storage quota tracking.

A user's usage counts their own My Media files plus every file in any group
*they created* (not groups they merely joined) - matching
accounts.models.User.storage_limit_gb's definition. Deliberately its own
module rather than living on the User model, so the accounts app doesn't
need to import storage's models.
"""
from django.db.models import Sum

from .models import MediaFile

BYTES_PER_GB = 1024 ** 3


def get_user_usage_bytes(user) -> int:
    personal = MediaFile.objects.filter(owner=user).aggregate(t=Sum("size_bytes"))["t"] or 0
    owned_groups = MediaFile.objects.filter(group__owner=user).aggregate(t=Sum("size_bytes"))["t"] or 0
    return personal + owned_groups


def get_user_limit_bytes(user) -> int:
    return user.storage_limit_gb * BYTES_PER_GB


def get_user_quota(user) -> dict:
    """Everything the profile/overview pages need in one query round-trip."""
    used = get_user_usage_bytes(user)
    limit = get_user_limit_bytes(user)
    percent = min(100, round((used / limit) * 100, 1)) if limit else 0
    return {
        "used_bytes": used,
        "limit_bytes": limit,
        "limit_gb": user.storage_limit_gb,
        "percent": percent,
        "over_limit": used > limit,
    }
