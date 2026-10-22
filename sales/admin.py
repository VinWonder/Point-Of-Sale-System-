from django.contrib import admin
from .models import Quotation, QuotationItem, Sale, SaleItem


class QuotationItemInline(admin.TabularInline):
    model = QuotationItem
    extra = 1


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'branch', 'status', 'total', 'created_at')
    list_filter = ('status', 'branch')
    inlines = [QuotationItemInline]


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'branch', 'status', 'payment_status', 'total', 'amount_paid', 'balance_due', 'created_at')
    list_filter = ('status', 'payment_status', 'sale_type', 'branch')
    readonly_fields = ('subtotal', 'total', 'tax_amount', 'amount_paid')
    inlines = [SaleItemInline]
