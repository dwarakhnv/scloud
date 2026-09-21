from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Profile", {"fields": ("display_name",)}),
        ("Storage quota", {"fields": ("storage_limit_gb",)}),
    )
    list_display = BaseUserAdmin.list_display + ("storage_limit_gb",)


admin.site.register(User, UserAdmin)
