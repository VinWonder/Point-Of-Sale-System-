from django.contrib import admin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'customer_type', 'phone_number', 'credit_limit', 'balance_owed', 'is_defaulter', 'is_active')
    search_fields = ('name', 'phone_number')
    list_filter = ('customer_type', 'is_active', 'created_at')

from .models import DebtPayment


@admin.register(DebtPayment)
class DebtPaymentAdmin(admin.ModelAdmin):
    list_display = ('customer', 'amount', 'method', 'reference', 'balance_after', 'received_by', 'created_at')
