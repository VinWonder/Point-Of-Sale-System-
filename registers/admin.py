from django.contrib import admin

from .models import Expense, Shift


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('id', 'cashier', 'branch', 'status', 'opened_at', 'closed_at',
                    'opening_float', 'expected_cash', 'counted_cash', 'variance')
    list_filter = ('status', 'branch')


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'branch', 'category', 'description', 'amount', 'paid_from_till', 'recorded_by')
    list_filter = ('category', 'branch', 'paid_from_till')
    search_fields = ('description', 'reference')
