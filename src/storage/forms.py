from django import forms

from .models import Group


class FolderCreateForm(forms.Form):
    name = forms.CharField(max_length=255)


class GroupCreateForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name"]


class GroupRenameForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name"]


class GroupInviteForm(forms.Form):
    username = forms.CharField(max_length=150)


class TagCreateForm(forms.Form):
    name = forms.CharField(max_length=100)


class ShareLinkForm(forms.Form):
    can_upload = forms.BooleanField(required=False)
    can_create_folders = forms.BooleanField(required=False)
    can_manage_tags = forms.BooleanField(required=False)
    can_delete_folders = forms.BooleanField(required=False)
