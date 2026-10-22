from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, AuditLog


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'get_full_name', 'role', 'branch', 'is_active')
    list_filter = ('role', 'branch', 'is_active')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('POS Info', {'fields': ('role', 'branch', 'phone_number')}),
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'entity')
    list_filter = ('entity',)
    readonly_fields = [f.name for f in AuditLog._meta.fields]
