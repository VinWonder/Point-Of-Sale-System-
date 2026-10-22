from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('sale', 'method', 'amount', 'status', 'mpesa_receipt_number', 'created_at')
    list_filter = ('method', 'status')
