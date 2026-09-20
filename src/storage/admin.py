from django.contrib import admin

from .models import Folder, Group, GroupMembership, MediaFile, ShareLink, Tag


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ("group", "user", "role", "joined_at")


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "group", "parent")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "group")


@admin.register(MediaFile)
class MediaFileAdmin(admin.ModelAdmin):
    list_display = (
        "filename", "owner", "group", "folder", "size_bytes", "thumbnail_status", "uploaded_at",
    )
    list_filter = ("thumbnail_status", "is_image", "is_video")


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = ("token", "created_by", "group", "folder", "is_active", "created_at")
