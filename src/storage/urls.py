from django.urls import path

from . import views

app_name = "storage"

urlpatterns = [
    path("", views.home, name="home"),

    # My Space
    path("my/", views.my_space, name="my_space"),
    path("my/folder/<int:folder_id>/", views.my_space, name="my_space_folder"),

    # Groups
    path("groups/", views.groups_list, name="groups_list"),
    path("groups/new/", views.group_create, name="group_create"),
    path("groups/<int:group_id>/", views.group_space, name="group_space"),
    path("groups/<int:group_id>/manage/", views.group_manage, name="group_manage"),
    path("groups/<int:group_id>/folder/<int:folder_id>/", views.group_space, name="group_folder"),
    path("groups/<int:group_id>/share/", views.share_group, name="share_group"),

    # Folders
    path("folder/create/", views.folder_create, name="folder_create"),
    path("folder/<int:folder_id>/move/", views.move_folder, name="move_folder"),
    path("folder/<int:folder_id>/share/", views.share_folder, name="share_folder"),
    path("folder/<int:folder_id>/delete/", views.delete_folder, name="delete_folder"),

    # Upload
    path("upload/", views.upload_files, name="upload_files"),
    path("upload/chunk/", views.upload_chunk, name="upload_chunk"),

    # Files
    path("file/<int:file_id>/", views.serve_file, name="serve_file"),
    path("file/<int:file_id>/thumbnail/", views.serve_thumbnail, name="serve_thumbnail"),
    path("file/<int:file_id>/status/", views.file_status, name="file_status"),
    path("file/<int:file_id>/move/", views.move_file, name="move_file"),
    path("file/<int:file_id>/delete/", views.delete_file, name="delete_file"),
    path("file/<int:file_id>/tag/", views.file_tag_toggle, name="file_tag_toggle"),

    # Tags
    path("tags/create/", views.tag_create, name="tag_create"),

    # Public sharing
    path("s/<str:token>/", views.shared_view, name="shared"),
    path("s/<str:token>/folder/<int:folder_id>/", views.shared_view, name="shared_folder"),
    path("s/<str:token>/upload/", views.shared_upload, name="shared_upload"),
    path("s/<str:token>/upload/chunk/", views.shared_upload_chunk, name="shared_upload_chunk"),
    path("s/<str:token>/folder/create/", views.shared_folder_create, name="shared_folder_create"),
    path("s/<str:token>/folder/<int:folder_id>/delete/", views.shared_delete_folder, name="shared_delete_folder"),
    path("s/<str:token>/tags/create/", views.shared_tag_create, name="shared_tag_create"),
    path("s/<str:token>/file/<int:file_id>/tag/", views.shared_tag_toggle, name="shared_tag_toggle"),
    path("share/<int:link_id>/revoke/", views.revoke_share, name="revoke_share"),
]
