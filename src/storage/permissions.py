from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Group


def get_group_or_403(user, group_id):
    group = get_object_or_404(Group, id=group_id)
    if not group.members.filter(id=user.id).exists() and group.owner_id != user.id:
        raise PermissionDenied("You are not a member of this group.")
    return group


def is_group_admin(user, group) -> bool:
    if group.owner_id == user.id:
        return True
    return group.groupmembership_set.filter(user=user, role="admin").exists()


def check_file_access(user, media_file):
    if media_file.owner_id:
        if media_file.owner_id != user.id:
            raise PermissionDenied("You do not have access to this file.")
    elif media_file.group_id:
        get_group_or_403(user, media_file.group_id)


def check_folder_access(user, folder):
    if folder.owner_id:
        if folder.owner_id != user.id:
            raise PermissionDenied("You do not have access to this folder.")
    elif folder.group_id:
        get_group_or_403(user, folder.group_id)
