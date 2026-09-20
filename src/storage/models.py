import secrets
from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse

from scloud.constants import Constants


class Group(models.Model):
    """A shared space multiple users can belong to."""

    name = models.CharField(max_length=150)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="owned_groups", on_delete=models.CASCADE
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="GroupMembership", related_name="scloud_groups"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def files_dir(self) -> Path:
        return Constants.files_dir("group", self.id)

    def thumbnails_dir(self) -> Path:
        return Constants.thumbnails_dir("group", self.id)


class GroupMembership(models.Model):
    ROLE_CHOICES = (("admin", "Admin"), ("member", "Member"))

    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("group", "user")

    def __str__(self):
        return f"{self.user} in {self.group} ({self.role})"


class Folder(models.Model):
    """A folder inside a user's My Space or a Group's space."""

    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self", null=True, blank=True, related_name="children", on_delete=models.CASCADE
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="folders",
        on_delete=models.CASCADE,
    )
    group = models.ForeignKey(
        Group, null=True, blank=True, related_name="folders", on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(owner__isnull=False, group__isnull=True)
                    | models.Q(owner__isnull=True, group__isnull=False)
                ),
                name="folder_owned_by_user_xor_group",
            )
        ]

    def __str__(self):
        return self.name

    def owner_type(self):
        return "user" if self.owner_id else "group"

    def owner_id_value(self):
        return self.owner_id or self.group_id

    def path_parts(self):
        parts = []
        node = self
        while node is not None:
            parts.append(node)
            node = node.parent
        return list(reversed(parts))

    def relative_path(self) -> Path:
        return Path(*[p.name for p in self.path_parts()])

    def full_path(self) -> Path:
        base = Constants.files_dir(self.owner_type(), self.owner_id_value())
        return base / self.relative_path()


class Tag(models.Model):
    """A tag, scoped to either a user's My Space or a Group."""

    name = models.CharField(max_length=100)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="tags",
        on_delete=models.CASCADE,
    )
    group = models.ForeignKey(
        Group, null=True, blank=True, related_name="tags", on_delete=models.CASCADE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name", "owner"], name="unique_tag_per_user"),
            models.UniqueConstraint(fields=["name", "group"], name="unique_tag_per_group"),
        ]

    def __str__(self):
        return self.name


class MediaFile(models.Model):
    """A single uploaded file (photo, video, or other media) and its metadata."""

    filename = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="files",
        on_delete=models.CASCADE,
    )
    group = models.ForeignKey(
        Group, null=True, blank=True, related_name="files", on_delete=models.CASCADE
    )
    folder = models.ForeignKey(
        Folder, null=True, blank=True, related_name="files", on_delete=models.CASCADE
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="uploaded_files", on_delete=models.SET_NULL,
        null=True,
    )

    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    is_image = models.BooleanField(default=False)
    is_video = models.BooleanField(default=False)

    thumbnail_filename = models.CharField(max_length=255, blank=True)
    thumbnail_status = models.CharField(
        max_length=20,
        choices=(("pending", "Pending"), ("ready", "Ready"), ("failed", "Failed"), ("none", "None")),
        default="pending",
    )

    tags = models.ManyToManyField(Tag, blank=True, related_name="files")

    # When the photo/video was actually taken (from EXIF/media metadata), used for
    # "media create date" sorting. Falls back to uploaded_at when unavailable.
    captured_at = models.DateTimeField(null=True, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(owner__isnull=False, group__isnull=True)
                    | models.Q(owner__isnull=True, group__isnull=False)
                ),
                name="file_owned_by_user_xor_group",
            )
        ]
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.filename

    def owner_type(self):
        return "user" if self.owner_id else "group"

    def owner_id_value(self):
        return self.owner_id or self.group_id

    def relative_dir(self) -> Path:
        if self.folder_id:
            return self.folder.relative_path()
        return Path(".")

    def disk_path(self) -> Path:
        base = Constants.files_dir(self.owner_type(), self.owner_id_value())
        return base / self.relative_dir() / self.filename

    def thumbnail_disk_path(self):
        if not self.thumbnail_filename:
            return None
        base = Constants.thumbnails_dir(self.owner_type(), self.owner_id_value())
        return base / self.thumbnail_filename

    def get_absolute_url(self):
        return reverse("storage:serve_file", args=[self.id])

    def get_thumbnail_url(self):
        if self.thumbnail_status == "ready" and self.thumbnail_filename:
            return reverse("storage:serve_thumbnail", args=[self.id])
        return None


class ShareLink(models.Model):
    """A public link granting read-only access to a folder or a group's space."""

    token = models.CharField(max_length=48, unique=True, default=secrets.token_urlsafe)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    group = models.ForeignKey(
        Group, null=True, blank=True, related_name="share_links", on_delete=models.CASCADE
    )
    folder = models.ForeignKey(
        Folder, null=True, blank=True, related_name="share_links", on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    # Permissions granted to anonymous visitors of this link.
    can_upload = models.BooleanField(default=False)
    can_create_folders = models.BooleanField(default=False)
    can_manage_tags = models.BooleanField(default=False)

    def __str__(self):
        return f"ShareLink({self.token})"

    def get_absolute_url(self):
        return reverse("storage:shared", args=[self.token])

    def is_valid(self):
        from django.utils import timezone
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    def owner_type(self):
        return "group" if self.group_id else "user"

    def owner_id_value(self):
        if self.group_id:
            return self.group_id
        if self.folder_id:
            return self.folder.owner_id
        return None
