from django.contrib import admin
from .models import Quotation, QuotationItem, Sale, SaleItem, SaleReturn, SaleReturnItem


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


class SaleReturnItemInline(admin.TabularInline):
    model = SaleReturnItem
    extra = 0
    readonly_fields = ('sale_item', 'quantity', 'restock', 'amount')


@admin.register(SaleReturn)
class SaleReturnAdmin(admin.ModelAdmin):
    list_display = ('id', 'sale', 'branch', 'refund_method', 'refund_amount', 'processed_by', 'created_at')
    list_filter = ('refund_method', 'branch')
    inlines = [SaleReturnItemInline]
