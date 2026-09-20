from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model so we control the identity our storage layer keys off."""

    display_name = models.CharField(max_length=150, blank=True)

    def name(self):
        return self.display_name or self.get_full_name() or self.username

    def __str__(self):
        return self.name()
