from django.contrib import admin
from .models import Category, Product, Stock, Supplier, SupplierPurchase


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'category', 'cost_price', 'sell_price', 'reorder_level', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'sku')


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
