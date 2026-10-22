from django.contrib import admin
from .models import Category, Product, Stock, StockMovement, Supplier, SupplierPurchase


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'brand', 'category', 'cost_price', 'sell_price', 'wholesale_price', 'reorder_level', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'sku', 'barcode', 'brand')


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('product', 'branch', 'quantity', 'is_low', 'updated_at')
    list_filter = ('branch',)
    search_fields = ('product__name', 'product__sku')


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    search_fields = ('name',)


@admin.register(SupplierPurchase)
class SupplierPurchaseAdmin(admin.ModelAdmin):
    list_display = ('product', 'supplier', 'branch', 'quantity', 'cost_price', 'is_paid', 'created_at')
    list_filter = ('branch', 'is_paid')


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'product', 'branch', 'kind', 'quantity', 'balance_after', 'reference', 'created_by')
    list_filter = ('kind', 'branch')
    search_fields = ('product__name', 'product__sku', 'reference')

    def has_change_permission(self, request, obj=None):
        return False
