import os
import shutil
import uuid
import zipfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, IntegerField, Sum, When
from django.db.models.functions import Coalesce, Lower
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from scloud.constants import Constants

from .forms import (
    FolderCreateForm, GroupCreateForm, GroupInviteForm, GroupRenameForm, ShareLinkForm,
    TagCreateForm,
)
from .media_metadata import extract_captured_at
from .models import Folder, Group, GroupMembership, MediaFile, ShareLink, Tag
from .permissions import check_file_access, check_folder_access, get_group_or_403, is_group_admin
from .quotas import get_user_quota
from .range_response import serve_file_with_range
from .thumbnails import queue_thumbnail

User = get_user_model()

VIEW_MODES = ("boxes", "list", "details")
SORT_MODES = (
    "name_asc", "name_desc",
    "uploaded_asc", "uploaded_desc",
    "captured_asc", "captured_desc",
    "type_asc", "type_desc",
    "size_asc", "size_desc",
)
DEFAULT_SORT_MODE = "name_asc"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _get_view_mode(request):
    mode = request.GET.get("view") or request.session.get("view_mode", "boxes")
    if mode not in VIEW_MODES:
        mode = "boxes"
    request.session["view_mode"] = mode
    return mode


def _get_sort_mode(request):
    mode = request.GET.get("sort") or request.session.get("sort_mode", DEFAULT_SORT_MODE)
    if mode not in SORT_MODES:
        mode = DEFAULT_SORT_MODE
    request.session["sort_mode"] = mode
    return mode


def _apply_sort(files_qs, sort_mode):
    descending = sort_mode.endswith("_desc")
    sign = "-" if descending else ""

    if sort_mode.startswith("name_"):
        return files_qs.annotate(_sort_name=Lower("filename")).order_by(f"{sign}_sort_name")
    if sort_mode.startswith("captured_"):
        return files_qs.annotate(_sort_date=Coalesce("captured_at", "uploaded_at")).order_by(
            f"{sign}_sort_date"
        )
    if sort_mode.startswith("type_"):
        # Group images, then videos, then everything else; alphabetical within each group.
        return files_qs.annotate(
            _sort_type=Case(
                When(is_image=True, then=0),
                When(is_video=True, then=1),
                default=2,
                output_field=IntegerField(),
            ),
            _sort_name=Lower("filename"),
        ).order_by(f"{sign}_sort_type", "_sort_name")
    if sort_mode.startswith("size_"):
        return files_qs.order_by(f"{sign}size_bytes")
    # uploaded_asc / uploaded_desc, and the fallback for an unrecognized mode.
    return files_qs.order_by(f"{sign}uploaded_at" if sort_mode.startswith("uploaded_") else "-uploaded_at")


def _breadcrumbs(folder):
    return folder.path_parts() if folder else []


def _available_tags(space, owner, group):
    if space == "group":
        return Tag.objects.filter(group=group).order_by("name")
    return Tag.objects.filter(owner=owner).order_by("name")


def _serialize_file(media_file):
    return {
        "id": media_file.id,
        "filename": media_file.filename,
        "url": media_file.get_absolute_url(),
        "thumb": media_file.get_thumbnail_url(),
        "is_image": media_file.is_image,
        "is_video": media_file.is_video,
        "thumbnail_status": media_file.thumbnail_status,
        "size_human": filesizeformat(media_file.size_bytes),
        "uploaded_at": media_file.uploaded_at.strftime("%b %d, %Y %H:%M")
        if hasattr(media_file.uploaded_at, "strftime") else "",
        "tag_ids": [t.id for t in media_file.tags.all()],
        "folder_id": media_file.folder_id,
    }


def _clean_name(raw_name: str) -> str:
    """Validate a user-supplied folder/file name. Raises ValueError with a
    human-readable message if it's not usable as a single path segment."""
    name = (raw_name or "").strip()
    if not name:
        raise ValueError("Name cannot be empty.")
    if "/" in name or "\\" in name:
        raise ValueError("Name cannot contain / or \\.")
    if name in (".", ".."):
        raise ValueError("Invalid name.")
    return name


def _check_sibling_folder_name(parent, owner, group, name, exclude_id=None):
    """Raise ValueError if another folder with this name already exists
    at the same level (same parent, same owner/group). Case-insensitive,
    since letting "Photos" and "photos" coexist is exactly the kind of
    thing that quietly produces duplicate/orphaned folders later."""
    qs = Folder.objects.filter(parent=parent, name__iexact=name)
    qs = qs.filter(group=group) if group else qs.filter(owner=owner)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    if qs.exists():
        raise ValueError(f'A folder named "{name}" already exists here.')


def _unique_filename(dest_dir: Path, filename: str) -> str:
    """Keep the original filename; if it collides, append a counter (Windows-Explorer style)."""
    candidate = filename
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 1
    while (dest_dir / candidate).exists():
        candidate = f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def _finalize_upload(*, src_path: Path, original_filename: str, owner, group, folder, uploaded_by,
                      content_type: str):
    """Move a fully-written file from a temp location into its final
    destination and create the MediaFile record. Shared by the simple
    (single-request) and chunked upload code paths."""
    owner_type = "group" if group else "user"
    owner_id = group.id if group else owner.id
    dest_dir = Constants.files_dir(owner_type, owner_id) / (
        folder.relative_path() if folder else Path(".")
    )
    dest_dir.mkdir(parents=True, exist_ok=True)

    target_name = _unique_filename(dest_dir, original_filename)
    target_path = dest_dir / target_name

    # os.replace is an atomic rename when src/dest share a drive (guaranteed
    # here since FILE_UPLOAD_TEMP_DIR lives under Constants.DATA_ROOT too) -
    # so finishing a multi-GB upload doesn't require re-copying its bytes.
    try:
        os.replace(src_path, target_path)
    except OSError:
        shutil.move(str(src_path), str(target_path))

    is_image = Constants.is_image(target_name)
    is_video = Constants.is_video(target_name)

    media_file = MediaFile.objects.create(
        filename=target_name,
        owner=owner,
        group=group,
        folder=folder,
        uploaded_by=uploaded_by,
        content_type=content_type or "",
        size_bytes=target_path.stat().st_size,
        is_image=is_image,
        is_video=is_video,
        captured_at=extract_captured_at(target_path, is_image),
        thumbnail_status="pending" if (is_image or is_video) else "none",
    )

    if is_image or is_video:
        queue_thumbnail(media_file.id)

    return media_file


# --------------------------------------------------------------------------
# My Media / Group browsing
# --------------------------------------------------------------------------

@login_required
def home(request):
    return redirect("storage:my_space")


@login_required
def my_space(request, folder_id=None):
    folder = None
    if folder_id:
        folder = get_object_or_404(Folder, id=folder_id, owner=request.user)

    return _render_browser(request, space="my", owner=request.user, group=None, folder=folder)


@login_required
def group_space(request, group_id, folder_id=None):
    group = get_group_or_403(request.user, group_id)
    folder = None
    if folder_id:
        folder = get_object_or_404(Folder, id=folder_id, group=group)

    return _render_browser(request, space="group", owner=None, group=group, folder=folder)


def _render_browser(request, space, owner, group, folder):
    subfolders_qs = Folder.objects.filter(parent=folder)
    files_qs = MediaFile.objects.all()

    if space == "group":
        subfolders_qs = subfolders_qs.filter(group=group)
        files_qs = files_qs.filter(group=group, folder=folder)
    else:
        subfolders_qs = subfolders_qs.filter(owner=owner)
        files_qs = files_qs.filter(owner=owner, folder=folder)

    tag_id = request.GET.get("tag")
    active_tag = None
    if tag_id:
        active_tag = get_object_or_404(Tag, id=tag_id)
        files_qs = files_qs.filter(tags=active_tag)

    sort_mode = _get_sort_mode(request)
    files_qs = _apply_sort(files_qs.prefetch_related("tags"), sort_mode)
    # Folders always sort by name, and are always listed ahead of files
    # (handled by the template rendering subfolders before files). Annotate
    # each with whether it's empty so the UI can skip the "are you sure?"
    # confirmation when deleting an empty folder.
    subfolders_qs = subfolders_qs.annotate(
        child_count=Count("children", distinct=True), file_count=Count("files", distinct=True),
    ).order_by("name")
    subfolders_list = list(subfolders_qs)

    if space == "group":
        all_folders = Folder.objects.filter(group=group).order_by("name")
    else:
        all_folders = Folder.objects.filter(owner=owner).order_by("name")

    files_list = list(files_qs)
    available_tags = _available_tags(space, owner, group)

    if folder:
        total_size_bytes = folder.total_size_bytes()
    else:
        # Viewing the root - "recursive size" is everything in this scope.
        scope_qs = MediaFile.objects.filter(group=group) if space == "group" \
            else MediaFile.objects.filter(owner=owner)
        total_size_bytes = scope_qs.aggregate(total=Sum("size_bytes"))["total"] or 0

    context = {
        "space": space,
        "group": group,
        "folder": folder,
        "breadcrumbs": _breadcrumbs(folder),
        "subfolders": subfolders_list,
        "folder_count": len(subfolders_list),
        "file_count": len(files_list),
        "total_size_bytes": total_size_bytes,
        "files": files_list,
        "all_folders": all_folders,
        "view_mode": _get_view_mode(request),
        "sort_mode": sort_mode,
        "available_tags": available_tags,
        "active_tag": active_tag,
        "is_group_admin": is_group_admin(request.user, group) if group else False,
        "files_data": [_serialize_file(f) for f in files_list],
        "folders_data": [{"id": f.id, "name": f.name} for f in all_folders],
        "tags_data": [{"id": t.id, "name": t.name} for t in available_tags],
        "chunk_size_bytes": Constants.UPLOAD_CHUNK_SIZE_BYTES,
        "max_upload_size_bytes": Constants.MAX_UPLOAD_SIZE_BYTES,
    }
    return render(request, "storage/browser.html", context)


@login_required
def groups_list(request):
    groups = Group.objects.filter(members=request.user).order_by("name")
    return render(request, "storage/groups_list.html", {"groups": groups})


@login_required
def system_overview(request):
    if not request.user.is_staff:
        raise PermissionDenied()

    disks = []
    for label, path in (
        ("Media files (DATA_ROOT)", Constants.DATA_ROOT),
        ("Database (DATABASE_PATH)", Constants.DATABASE_PATH.parent),
    ):
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        disks.append({
            "label": label,
            "path": str(path),
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
        })
    # Two different paths often land on the same physical/virtual drive
    # (e.g. DATA_ROOT and DATABASE_PATH both under the same mount) - flag
    # that in the template rather than silently showing identical numbers
    # twice with no explanation.
    for i, disk in enumerate(disks):
        disk["shared_with"] = [
            other["label"] for j, other in enumerate(disks)
            if j != i and other["total"] == disk["total"] and other["free"] == disk["free"]
        ]

    user_rows = []
    for user in User.objects.order_by("username"):
        quota = get_user_quota(user)
        user_rows.append({
            "user": user,
            "owned_groups": Group.objects.filter(owner=user).count(),
            **quota,
        })
    user_rows.sort(key=lambda r: r["used_bytes"], reverse=True)

    return render(
        request, "storage/system_overview.html", {"disks": disks, "user_rows": user_rows},
    )


@login_required
def group_create(request):
    if request.method == "POST":
        form = GroupCreateForm(request.POST)
        if form.is_valid():
            group = form.save(commit=False)
            group.owner = request.user
            group.save()
            GroupMembership.objects.create(group=group, user=request.user, role="admin")
            messages.success(request, f"Group '{group.name}' created.")
            return redirect("storage:group_space", group_id=group.id)
    else:
        form = GroupCreateForm()
    return render(request, "storage/group_create.html", {"form": form})


@login_required
def group_manage(request, group_id):
    group = get_group_or_403(request.user, group_id)
    if not is_group_admin(request.user, group):
        raise PermissionDenied("Only group admins can manage members.")

    invite_form = GroupInviteForm()
    rename_form = GroupRenameForm(instance=group)

    if request.method == "POST":
        if "invite" in request.POST:
            invite_form = GroupInviteForm(request.POST)
            if invite_form.is_valid():
                username = invite_form.cleaned_data["username"]
                try:
                    user = User.objects.get(username=username)
                    GroupMembership.objects.get_or_create(group=group, user=user)
                    messages.success(request, f"Added {username} to the group.")
                except User.DoesNotExist:
                    messages.error(request, f"No user named '{username}'.")
        elif "remove_member" in request.POST:
            member_id = request.POST.get("remove_member")
            GroupMembership.objects.filter(group=group, user_id=member_id).exclude(
                user=group.owner
            ).delete()
            messages.success(request, "Member removed.")
        elif "rename_group" in request.POST:
            rename_form = GroupRenameForm(request.POST, instance=group)
            if rename_form.is_valid():
                rename_form.save()
                messages.success(request, "Group renamed.")
        return redirect("storage:group_manage", group_id=group.id)

    memberships = GroupMembership.objects.filter(group=group).select_related("user")
    return render(
        request,
        "storage/group_manage.html",
        {
            "group": group,
            "memberships": memberships,
            "invite_form": invite_form,
            "rename_form": rename_form,
        },
    )


# --------------------------------------------------------------------------
# Folders
# --------------------------------------------------------------------------

@login_required
@require_POST
def folder_create(request):
    space = request.POST.get("space")
    group_id = request.POST.get("group_id")
    parent_id = request.POST.get("folder_id") or None
    form = FolderCreateForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Please provide a folder name.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    parent = None
    group = None
    owner = None

    if space == "group":
        group = get_group_or_403(request.user, group_id)
        if parent_id:
            parent = get_object_or_404(Folder, id=parent_id, group=group)
    else:
        owner = request.user
        if parent_id:
            parent = get_object_or_404(Folder, id=parent_id, owner=owner)

    try:
        _check_sibling_folder_name(parent, owner, group, form.cleaned_data["name"])
    except ValueError as e:
        messages.error(request, str(e))
        return redirect(request.META.get("HTTP_REFERER", "/"))

    Folder.objects.create(name=form.cleaned_data["name"], parent=parent, owner=owner, group=group)
    messages.success(request, "Folder created.")

    if space == "group":
        return redirect("storage:group_folder", group_id=group.id, folder_id=parent.id) if parent \
            else redirect("storage:group_space", group_id=group.id)
    return redirect("storage:my_space_folder", folder_id=parent.id) if parent \
        else redirect("storage:my_space")


# --------------------------------------------------------------------------
# Upload (simple, single-request path - used for small files)
# --------------------------------------------------------------------------

@login_required
@require_POST
def upload_files(request):
    space = request.POST.get("space")
    group_id = request.POST.get("group_id")
    folder_id = request.POST.get("folder_id") or None

    group = None
    owner = None
    folder = None

    if space == "group":
        group = get_group_or_403(request.user, group_id)
        if folder_id:
            folder = get_object_or_404(Folder, id=folder_id, group=group)
    else:
        owner = request.user
        if folder_id:
            folder = get_object_or_404(Folder, id=folder_id, owner=owner)

    files = request.FILES.getlist("files")
    if not files:
        return HttpResponseBadRequest("No files provided.")

    created_ids = []
    for uploaded in files:
        owner_type = "group" if group else "user"
        owner_id = group.id if group else owner.id
        tmp_dir = Constants.files_dir(owner_type, owner_id) / (
            folder.relative_path() if folder else Path(".")
        )
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f".incoming-{uuid.uuid4().hex}"

        with open(tmp_path, "wb") as out:
            for chunk in uploaded.chunks():
                out.write(chunk)

        media_file = _finalize_upload(
            src_path=tmp_path, original_filename=uploaded.name, owner=owner, group=group,
            folder=folder, uploaded_by=request.user, content_type=uploaded.content_type,
        )
        created_ids.append(media_file.id)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"created": created_ids})

    messages.success(request, f"Uploaded {len(created_ids)} file(s).")
    return redirect(request.META.get("HTTP_REFERER", "/"))


# --------------------------------------------------------------------------
# Upload (chunked path - used for large files so a dropped connection only
# has to retry one chunk instead of the whole multi-GB file)
# --------------------------------------------------------------------------

def _resolve_upload_scope(request, space, group_id, folder_id):
    group = None
    owner = None
    folder = None
    if space == "group":
        group = get_group_or_403(request.user, group_id)
        if folder_id:
            folder = get_object_or_404(Folder, id=folder_id, group=group)
    else:
        owner = request.user
        if folder_id:
            folder = get_object_or_404(Folder, id=folder_id, owner=owner)
    return owner, group, folder


@login_required
@require_POST
def upload_chunk(request):
    space = request.POST.get("space")
    group_id = request.POST.get("group_id")
    folder_id = request.POST.get("folder_id") or None
    owner, group, folder = _resolve_upload_scope(request, space, group_id, folder_id)
    return _handle_chunk(request, owner=owner, group=group, folder=folder, uploaded_by=request.user)


def _handle_chunk(request, *, owner, group, folder, uploaded_by):
    upload_id = request.POST.get("upload_id")
    filename = request.POST.get("filename")
    chunk_index = int(request.POST.get("chunk_index", 0))
    total_chunks = int(request.POST.get("total_chunks", 1))
    chunk = request.FILES.get("chunk")

    if not (upload_id and filename and chunk):
        return HttpResponseBadRequest("Missing upload data.")

    safe_id = "".join(c for c in upload_id if c.isalnum() or c in "-_")
    tmp_path = Constants.upload_tmp_dir() / f"{request.user.id if request.user.is_authenticated else 'anon'}_{safe_id}.part"

    offset = chunk_index * Constants.UPLOAD_CHUNK_SIZE_BYTES
    if offset + chunk.size > Constants.MAX_UPLOAD_SIZE_BYTES:
        return JsonResponse({"error": "File exceeds the maximum upload size."}, status=400)

    mode = "r+b" if tmp_path.exists() else "wb"
    with open(tmp_path, mode) as out:
        out.seek(offset)
        for piece in chunk.chunks():
            out.write(piece)

    if chunk_index < total_chunks - 1:
        return JsonResponse({"ok": True, "received": chunk_index})

    content_type = request.POST.get("content_type", "")
    media_file = _finalize_upload(
        src_path=tmp_path, original_filename=filename, owner=owner, group=group, folder=folder,
        uploaded_by=uploaded_by, content_type=content_type,
    )
    return JsonResponse({"ok": True, "done": True, "file_id": media_file.id})


# --------------------------------------------------------------------------
# Serving files & thumbnails
# --------------------------------------------------------------------------

def _authorize_media_access(request, media_file):
    """Allow access if the user has direct rights, or a valid share token
    covers this file's folder/group."""
    token = request.GET.get("share")
    if token:
        link = ShareLink.objects.filter(token=token).first()
        if link and link.is_valid() and _media_file_in_share_scope(link, media_file):
            return
        raise PermissionDenied("Invalid or expired share link.")

    if not request.user.is_authenticated:
        raise PermissionDenied("Sign in required.")
    check_file_access(request.user, media_file)


def serve_file(request, file_id):
    media_file = get_object_or_404(MediaFile, id=file_id)
    _authorize_media_access(request, media_file)
    return serve_file_with_range(
        request, media_file.disk_path(), filename=media_file.filename,
        content_type=media_file.content_type or None,
    )


def serve_thumbnail(request, file_id):
    media_file = get_object_or_404(MediaFile, id=file_id)
    _authorize_media_access(request, media_file)
    thumb_path = media_file.thumbnail_disk_path()
    if not thumb_path or not thumb_path.exists():
        return HttpResponse(status=404)
    return serve_file_with_range(request, thumb_path, content_type="image/jpeg")


@login_required
def file_status(request, file_id):
    """Polled by the browser right after upload so a freshly-created file's
    box can swap in its thumbnail once background generation finishes."""
    media_file = get_object_or_404(MediaFile, id=file_id)
    check_file_access(request.user, media_file)
    return JsonResponse({
        "status": media_file.thumbnail_status,
        "thumbnail_url": media_file.get_thumbnail_url(),
    })


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------

@login_required
@require_POST
def tag_create(request):
    space = request.POST.get("space")
    group_id = request.POST.get("group_id")
    form = TagCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": "Invalid tag name."}, status=400)

    name = form.cleaned_data["name"].strip()
    if space == "group":
        group = get_group_or_403(request.user, group_id)
        tag, _ = Tag.objects.get_or_create(name=name, group=group)
    else:
        tag, _ = Tag.objects.get_or_create(name=name, owner=request.user)

    return JsonResponse({"id": tag.id, "name": tag.name})


@login_required
@require_POST
def file_tag_toggle(request, file_id):
    media_file = get_object_or_404(MediaFile, id=file_id)
    check_file_access(request.user, media_file)

    tag_id = request.POST.get("tag_id")
    tag = get_object_or_404(Tag, id=tag_id)

    if media_file.tags.filter(id=tag.id).exists():
        media_file.tags.remove(tag)
        added = False
    else:
        media_file.tags.add(tag)
        added = True

    return JsonResponse({"added": added, "tag_id": tag.id, "tag_name": tag.name})


# --------------------------------------------------------------------------
# Move files / folders
# --------------------------------------------------------------------------

@login_required
@require_POST
def move_file(request, file_id):
    media_file = get_object_or_404(MediaFile, id=file_id)
    check_file_access(request.user, media_file)

    dest_folder_id = request.POST.get("dest_folder_id") or None
    dest_folder = None
    if dest_folder_id:
        dest_folder = get_object_or_404(Folder, id=dest_folder_id)
        check_folder_access(request.user, dest_folder)
        # Folders must stay within the same owner/group scope.
        if media_file.owner_id and dest_folder.owner_id != media_file.owner_id:
            raise PermissionDenied("Cannot move file across spaces.")
        if media_file.group_id and dest_folder.group_id != media_file.group_id:
            raise PermissionDenied("Cannot move file across spaces.")

    old_path = media_file.disk_path()
    owner_type = media_file.owner_type()
    owner_id = media_file.owner_id_value()
    new_dir = Constants.files_dir(owner_type, owner_id) / (
        dest_folder.relative_path() if dest_folder else Path(".")
    )
    new_dir.mkdir(parents=True, exist_ok=True)
    new_name = _unique_filename(new_dir, media_file.filename) if new_dir != old_path.parent else media_file.filename
    new_path = new_dir / new_name

    if old_path != new_path:
        shutil.move(str(old_path), str(new_path))

    media_file.folder = dest_folder
    media_file.filename = new_name
    media_file.save(update_fields=["folder", "filename"])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    messages.success(request, f"Moved {media_file.filename}.")
    return redirect(request.META.get("HTTP_REFERER", "/"))


@login_required
@require_POST
def move_folder(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id)
    check_folder_access(request.user, folder)

    dest_parent_id = request.POST.get("dest_folder_id") or None
    dest_parent = None
    if dest_parent_id:
        dest_parent = get_object_or_404(Folder, id=dest_parent_id)
        check_folder_access(request.user, dest_parent)
        if folder.owner_id and dest_parent.owner_id != folder.owner_id:
            raise PermissionDenied("Cannot move folder across spaces.")
        if folder.group_id and dest_parent.group_id != folder.group_id:
            raise PermissionDenied("Cannot move folder across spaces.")
        # Prevent moving a folder into its own descendant.
        node = dest_parent
        while node is not None:
            if node.id == folder.id:
                raise PermissionDenied("Cannot move a folder into itself.")
            node = node.parent

    try:
        _check_sibling_folder_name(
            dest_parent, folder.owner, folder.group, folder.name, exclude_id=folder.id
        )
    except ValueError as e:
        messages.error(request, str(e))
        return redirect(request.META.get("HTTP_REFERER", "/"))

    old_path = folder.full_path()
    folder.parent = dest_parent
    folder.save(update_fields=["parent"])
    new_path = folder.full_path()

    if old_path != new_path:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        if old_path.exists():
            shutil.move(str(old_path), str(new_path))

    messages.success(request, f"Moved folder {folder.name}.")
    return redirect(request.META.get("HTTP_REFERER", "/"))


@login_required
@require_POST
def rename_folder(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id)
    check_folder_access(request.user, folder)

    try:
        new_name = _clean_name(request.POST.get("name"))
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)

    if new_name != folder.name:
        try:
            _check_sibling_folder_name(
                folder.parent, folder.owner, folder.group, new_name, exclude_id=folder.id
            )
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)

        # Folder.relative_path()/full_path() are derived live from `name`, so
        # every descendant folder and file automatically resolves to the new
        # path once this save() commits - nothing else in the DB needs to
        # change. Moving this one directory on disk brings the whole
        # subtree along with it, since it's just an OS-level rename.
        old_path = folder.full_path()
        prospective_path = old_path.parent / new_name
        if prospective_path != old_path and prospective_path.exists():
            return JsonResponse(
                {"error": "A folder with that name already exists here."}, status=400
            )

        folder.name = new_name
        folder.save(update_fields=["name"])
        new_path = folder.full_path()

        if old_path != new_path and old_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_path), str(new_path))

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "name": folder.name})
    messages.success(request, f"Renamed to '{folder.name}'.")
    return redirect(request.META.get("HTTP_REFERER", "/"))


@login_required
@require_POST
def rename_file(request, file_id):
    media_file = get_object_or_404(MediaFile, id=file_id)
    check_file_access(request.user, media_file)

    try:
        new_name = _clean_name(request.POST.get("name"))
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)

    if new_name != media_file.filename:
        old_path = media_file.disk_path()
        dest_dir = old_path.parent
        final_name = _unique_filename(dest_dir, new_name)
        new_path = dest_dir / final_name

        if old_path.exists():
            shutil.move(str(old_path), str(new_path))

        media_file.filename = final_name
        media_file.is_image = Constants.is_image(final_name)
        media_file.is_video = Constants.is_video(final_name)
        media_file.save(update_fields=["filename", "is_image", "is_video"])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "filename": media_file.filename})
    messages.success(request, f"Renamed to '{media_file.filename}'.")
    return redirect(request.META.get("HTTP_REFERER", "/"))


@login_required
@require_POST
def delete_file(request, file_id):
    media_file = get_object_or_404(MediaFile, id=file_id)
    check_file_access(request.user, media_file)

    path = media_file.disk_path()
    if path.exists():
        path.unlink()
    thumb_path = media_file.thumbnail_disk_path()
    if thumb_path and thumb_path.exists():
        thumb_path.unlink()

    media_file.delete()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    messages.success(request, "File deleted.")
    return redirect(request.META.get("HTTP_REFERER", "/"))


def _delete_folder_and_contents(folder):
    """Recursively delete a folder: every file inside it or any descendant
    folder is removed from disk, then the folder itself is deleted (which
    cascades to remove the Folder/MediaFile rows in the DB)."""
    subtree_ids = folder.subtree_ids()
    for media_file in MediaFile.objects.filter(folder_id__in=subtree_ids):
        path = media_file.disk_path()
        if path.exists():
            path.unlink()
        thumb_path = media_file.thumbnail_disk_path()
        if thumb_path and thumb_path.exists():
            thumb_path.unlink()

    disk_path = folder.full_path()
    if disk_path.exists():
        shutil.rmtree(disk_path, ignore_errors=True)

    folder.delete()


@login_required
@require_POST
def delete_folder(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id)
    check_folder_access(request.user, folder)
    name = folder.name
    _delete_folder_and_contents(folder)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    messages.success(request, f"Deleted folder '{name}'.")
    return redirect(request.META.get("HTTP_REFERER", "/"))


# --------------------------------------------------------------------------
# Bulk download (zip)
# --------------------------------------------------------------------------
# Multi-select "Download" for 2+ files builds a zip server-side instead of
# firing off one HTTP request per file - much cheaper for everyone once you
# get past a handful of files. The zip is staged under Constants.DATA_ROOT
# (never the database's drive - see Constants.zip_tmp_dir) and is deleted
# the moment it's finished streaming, whether that's because the download
# completed normally or the connection dropped partway through (both paths
# run the same `finally` block below). A lazy sweep for anything left behind
# by a hard crash runs at the start of every new zip request.

def _cleanup_stale_zips():
    cutoff = timezone.now().timestamp() - (Constants.ZIP_TMP_MAX_AGE_HOURS * 3600)
    zip_dir = Constants.zip_tmp_dir()
    try:
        entries = os.scandir(zip_dir)
    except FileNotFoundError:
        return
    with entries:
        for entry in entries:
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    os.unlink(entry.path)
            except OSError:
                pass


def _dedupe_arcname(used_names: set, filename: str) -> str:
    if filename not in used_names:
        used_names.add(filename)
        return filename
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 1
    while True:
        candidate = f"{stem} ({counter}){suffix}"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        counter += 1


@login_required
@require_POST
def create_zip_download(request):
    file_ids = request.POST.getlist("file_ids")
    if not file_ids:
        return JsonResponse({"error": "No files selected."}, status=400)

    media_files = []
    for file_id in file_ids:
        media_file = get_object_or_404(MediaFile, id=file_id)
        check_file_access(request.user, media_file)
        media_files.append(media_file)

    _cleanup_stale_zips()

    zip_name = f"{request.user.id}_{uuid.uuid4().hex}.zip"
    zip_path = Constants.zip_tmp_dir() / zip_name

    used_names = set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for media_file in media_files:
            src = media_file.disk_path()
            if not src.exists():
                continue
            arcname = _dedupe_arcname(used_names, media_file.filename)
            zf.write(src, arcname=arcname)

    return JsonResponse({"url": reverse("storage:serve_zip_download", args=[zip_name])})


def _stream_and_delete(path, chunk_size=1024 * 1024):
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    finally:
        # Runs whether the loop above finished normally or the client
        # disconnected mid-stream (Python calls .close() on an abandoned
        # generator, which raises GeneratorExit at the current yield and
        # unwinds straight into this finally block either way).
        try:
            os.unlink(path)
        except OSError:
            pass


@login_required
def serve_zip_download(request, zip_name):
    # Zip filenames are prefixed with the creating user's id as a basic
    # ownership check - the random uuid after it already makes them
    # unguessable, this just stops one user's download link from working
    # for anyone who happens to be logged in as someone else.
    if not zip_name.startswith(f"{request.user.id}_") or "/" in zip_name or "\\" in zip_name:
        raise PermissionDenied()

    zip_path = Constants.zip_tmp_dir() / zip_name
    if not zip_path.exists():
        return HttpResponse(status=404)

    response = StreamingHttpResponse(_stream_and_delete(zip_path), content_type="application/zip")
    response["Content-Length"] = zip_path.stat().st_size
    response["Content-Disposition"] = 'attachment; filename="scloud-download.zip"'
    return response


# --------------------------------------------------------------------------
# Public share links
# --------------------------------------------------------------------------

def _share_permission_kwargs(request):
    form = ShareLinkForm(request.POST)
    form.is_valid()
    return {
        "can_upload": form.cleaned_data.get("can_upload", False),
        "can_create_folders": form.cleaned_data.get("can_create_folders", False),
        "can_manage_tags": form.cleaned_data.get("can_manage_tags", False),
        "can_delete_folders": form.cleaned_data.get("can_delete_folders", False),
    }


@login_required
@require_POST
def share_folder(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id)
    check_folder_access(request.user, folder)
    link = ShareLink.objects.create(
        created_by=request.user, folder=folder, group=folder.group,
        **_share_permission_kwargs(request),
    )
    messages.success(request, "Share link created.")
    return _redirect_with_copy(request.META.get("HTTP_REFERER", "/"), link)


@login_required
@require_POST
def share_group(request, group_id):
    group = get_group_or_403(request.user, group_id)
    link = ShareLink.objects.create(created_by=request.user, group=group, **_share_permission_kwargs(request))
    messages.success(request, "Share link created.")
    return _redirect_with_copy(
        redirect("storage:group_manage", group_id=group.id).url, link,
    )


def _redirect_with_copy(url, link):
    """Redirect back with a marker telling the page's JS to auto-copy the
    freshly created share link to the clipboard."""
    separator = "&" if "?" in url else "?"
    return redirect(f"{url}{separator}copied_share={link.id}")


def _get_valid_link(token):
    link = get_object_or_404(ShareLink, token=token)
    if not link.is_valid():
        return None
    return link


def _share_scope(link):
    """Return (owner, group, root_folder) describing what a share link exposes."""
    folder = link.folder
    group = link.group
    owner = folder.owner if (folder and folder.owner_id) else None
    return owner, group, folder


def _resolve_shared_folder(link, folder_id):
    """Validate that `folder_id` (if given) is actually within this share
    link's scope - either the shared folder itself or nested somewhere below
    it, or (for a whole-group share) anywhere in that group - and return it.
    Returns the link's root folder (possibly None, meaning the group root)
    when no folder_id is given. Raises PermissionDenied otherwise. This is
    what makes sharing recursive: a link to a folder implicitly shares
    everything nested inside it too."""
    root_folder, group = link.folder, link.group

    if not folder_id:
        return root_folder

    folder = get_object_or_404(Folder, id=folder_id)
    if root_folder:
        if not folder.is_within(root_folder):
            raise PermissionDenied("That folder is outside this share link.")
    elif group:
        if folder.group_id != group.id:
            raise PermissionDenied("That folder is outside this share link.")
    else:
        raise PermissionDenied()
    return folder


def _media_file_in_share_scope(link, media_file) -> bool:
    if link.folder_id:
        return bool(media_file.folder_id) and media_file.folder.is_within(link.folder)
    if link.group_id:
        return media_file.group_id == link.group_id
    return False


def _shared_breadcrumbs(link, current_folder):
    """Breadcrumb chain for the shared view - starts at the shared folder
    itself (or the group root), never showing private ancestors above it."""
    if not current_folder:
        return []
    chain = current_folder.path_parts()
    if link.folder_id:
        for i, node in enumerate(chain):
            if node.id == link.folder_id:
                return chain[i:]
    return chain


@ensure_csrf_cookie
def shared_view(request, token, folder_id=None):
    link = _get_valid_link(token)
    if not link:
        return render(request, "storage/share_expired.html", status=410)

    owner, group, root_folder = _share_scope(link)
    current_folder = _resolve_shared_folder(link, folder_id)

    if current_folder:
        # parent is an exact FK to one specific Folder row, so this is
        # already scoped correctly - only this folder's own children.
        subfolders_qs = Folder.objects.filter(parent=current_folder)
    elif group:
        # Root of a whole-group share: `parent=None` alone would match
        # every top-level folder for every user/group in the database, not
        # just this one's - group=group is what actually scopes it.
        subfolders_qs = Folder.objects.filter(parent=None, group=group)
    else:
        subfolders_qs = Folder.objects.none()

    subfolders_list = list(subfolders_qs.annotate(
        child_count=Count("children", distinct=True), file_count=Count("files", distinct=True),
    ).order_by("name"))

    if current_folder:
        files = MediaFile.objects.filter(folder=current_folder)
    elif group:
        files = MediaFile.objects.filter(group=group, folder=None)
    else:
        files = MediaFile.objects.none()

    sort_mode = _get_sort_mode(request)
    files = list(_apply_sort(files.prefetch_related("tags"), sort_mode))

    space = "group" if group else "my"
    tags = _available_tags(space, owner, group)

    if current_folder:
        total_size_bytes = current_folder.total_size_bytes()
    elif group:
        total_size_bytes = MediaFile.objects.filter(group=group).aggregate(
            total=Sum("size_bytes")
        )["total"] or 0
    else:
        total_size_bytes = 0

    return render(
        request,
        "storage/shared.html",
        {
            "link": link, "folder": current_folder, "group": group,
            "breadcrumbs": _shared_breadcrumbs(link, current_folder),
            "subfolders": subfolders_list,
            "folder_count": len(subfolders_list),
            "file_count": len(files),
            "total_size_bytes": total_size_bytes,
            "files": files, "sort_mode": sort_mode, "available_tags": tags,
            "files_data": [_serialize_file(f) for f in files],
            "tags_data": [{"id": t.id, "name": t.name} for t in tags],
            "share_url": request.build_absolute_uri(link.get_absolute_url()),
        },
    )


@require_POST
def shared_upload(request, token):
    link = _get_valid_link(token)
    if not link or not link.can_upload:
        raise PermissionDenied("Uploads are not allowed on this link.")

    owner, group, _ = _share_scope(link)
    folder = _resolve_shared_folder(link, request.POST.get("folder_id"))
    files = request.FILES.getlist("files")
    if not files:
        return HttpResponseBadRequest("No files provided.")

    created_ids = []
    for uploaded in files:
        owner_type = "group" if group else "user"
        owner_id = group.id if group else owner.id
        tmp_dir = Constants.files_dir(owner_type, owner_id) / (
            folder.relative_path() if folder else Path(".")
        )
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f".incoming-{uuid.uuid4().hex}"
        with open(tmp_path, "wb") as out:
            for chunk in uploaded.chunks():
                out.write(chunk)
        media_file = _finalize_upload(
            src_path=tmp_path, original_filename=uploaded.name, owner=owner, group=group,
            folder=folder, uploaded_by=link.created_by, content_type=uploaded.content_type,
        )
        created_ids.append(media_file.id)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"created": created_ids})
    messages.success(request, f"Uploaded {len(created_ids)} file(s).")
    return redirect("storage:shared", token=token)


@require_POST
def shared_upload_chunk(request, token):
    link = _get_valid_link(token)
    if not link or not link.can_upload:
        raise PermissionDenied("Uploads are not allowed on this link.")
    owner, group, _ = _share_scope(link)
    folder = _resolve_shared_folder(link, request.POST.get("folder_id"))
    return _handle_chunk(request, owner=owner, group=group, folder=folder, uploaded_by=link.created_by)


@require_POST
def shared_folder_create(request, token):
    link = _get_valid_link(token)
    if not link or not link.can_create_folders:
        raise PermissionDenied("Creating folders is not allowed on this link.")

    owner, group, _ = _share_scope(link)
    parent = _resolve_shared_folder(link, request.POST.get("folder_id"))
    form = FolderCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please provide a folder name.")
    else:
        try:
            _check_sibling_folder_name(parent, owner, group, form.cleaned_data["name"])
        except ValueError as e:
            messages.error(request, str(e))
        else:
            Folder.objects.create(name=form.cleaned_data["name"], parent=parent, owner=owner, group=group)
            messages.success(request, "Folder created.")

    if parent:
        return redirect("storage:shared_folder", token=token, folder_id=parent.id)
    return redirect("storage:shared", token=token)


@require_POST
def shared_delete_folder(request, token, folder_id):
    link = _get_valid_link(token)
    if not link or not link.can_delete_folders:
        raise PermissionDenied("Deleting folders is not allowed on this link.")

    folder = _resolve_shared_folder(link, folder_id)
    if not folder:
        raise PermissionDenied()
    # Never allow deleting the share's own root folder out from under it.
    if link.folder_id and folder.id == link.folder_id:
        raise PermissionDenied("Cannot delete the shared folder itself.")

    parent_id = folder.parent_id
    name = folder.name
    _delete_folder_and_contents(folder)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    messages.success(request, f"Deleted folder '{name}'.")
    if parent_id:
        return redirect("storage:shared_folder", token=token, folder_id=parent_id)
    return redirect("storage:shared", token=token)


@require_POST
def shared_rename_folder(request, token, folder_id):
    link = _get_valid_link(token)
    if not link or not link.can_delete_folders:
        raise PermissionDenied("Managing folders is not allowed on this link.")

    folder = _resolve_shared_folder(link, folder_id)
    if not folder:
        raise PermissionDenied()
    if link.folder_id and folder.id == link.folder_id:
        raise PermissionDenied("Cannot rename the shared folder itself.")

    try:
        new_name = _clean_name(request.POST.get("name"))
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)

    if new_name != folder.name:
        try:
            _check_sibling_folder_name(
                folder.parent, folder.owner, folder.group, new_name, exclude_id=folder.id
            )
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)

        old_path = folder.full_path()
        prospective_path = old_path.parent / new_name
        if prospective_path != old_path and prospective_path.exists():
            return JsonResponse(
                {"error": "A folder with that name already exists here."}, status=400
            )
        folder.name = new_name
        folder.save(update_fields=["name"])
        new_path = folder.full_path()
        if old_path != new_path and old_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_path), str(new_path))

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "name": folder.name})
    messages.success(request, f"Renamed to '{folder.name}'.")
    return redirect("storage:shared_folder", token=token, folder_id=folder.id)


@require_POST
def shared_tag_create(request, token):
    link = _get_valid_link(token)
    if not link or not link.can_manage_tags:
        raise PermissionDenied("Managing tags is not allowed on this link.")

    owner, group, _ = _share_scope(link)
    form = TagCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": "Invalid tag name."}, status=400)

    name = form.cleaned_data["name"].strip()
    if group:
        tag, _ = Tag.objects.get_or_create(name=name, group=group)
    else:
        tag, _ = Tag.objects.get_or_create(name=name, owner=owner)
    return JsonResponse({"id": tag.id, "name": tag.name})


@require_POST
def shared_tag_toggle(request, token, file_id):
    link = _get_valid_link(token)
    if not link or not link.can_manage_tags:
        raise PermissionDenied("Managing tags is not allowed on this link.")

    media_file = get_object_or_404(MediaFile, id=file_id)
    if not _media_file_in_share_scope(link, media_file):
        raise PermissionDenied()

    tag_id = request.POST.get("tag_id")
    tag = get_object_or_404(Tag, id=tag_id)
    if media_file.tags.filter(id=tag.id).exists():
        media_file.tags.remove(tag)
        added = False
    else:
        media_file.tags.add(tag)
        added = True
    return JsonResponse({"added": added, "tag_id": tag.id, "tag_name": tag.name})


@login_required
def revoke_share(request, link_id):
    link = get_object_or_404(ShareLink, id=link_id, created_by=request.user)
    link.is_active = False
    link.save(update_fields=["is_active"])
    messages.success(request, "Share link revoked.")
    return redirect(request.META.get("HTTP_REFERER", "/"))
