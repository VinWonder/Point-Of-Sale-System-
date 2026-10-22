from django.contrib import admin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number', 'credit_limit', 'balance_owed', 'is_defaulter')
    search_fields = ('name', 'phone_number')
    list_filter = ('created_at',)

from .models import DebtPayment


@admin.register(DebtPayment)
class DebtPaymentAdmin(admin.ModelAdmin):
    list_display = ('customer', 'amount', 'received_by', 'created_at')
