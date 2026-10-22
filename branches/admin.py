from django.contrib import admin
from .models import Branch, StockTransfer


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'phone_number', 'is_active')
    search_fields = ('name', 'location')


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = ('product', 'from_branch', 'to_branch', 'quantity', 'status', 'created_at')
    list_filter = ('status', 'from_branch', 'to_branch')
