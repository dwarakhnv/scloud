from django.contrib.auth.models import AbstractUser
from django.db import models


DEFAULT_STORAGE_LIMIT_GB = 64


class User(AbstractUser):
    """Custom user model so we control the identity our storage layer keys off."""

    display_name = models.CharField(max_length=150, blank=True)

    # Storage quota in GB, counting this user's own My Media files plus every
    # file in any group they created (not groups they merely joined). Edited
    # by staff/superusers via the Django admin. Enforcement/display lives in
    # storage.quotas rather than here, to keep this app free of a dependency
    # on the storage app's models.
    storage_limit_gb = models.PositiveIntegerField(
        default=DEFAULT_STORAGE_LIMIT_GB,
        help_text="Maximum storage in GB for this user's My Media plus any groups they created.",
    )

    def name(self):
        return self.display_name or self.get_full_name() or self.username

    def __str__(self):
        return self.name()
