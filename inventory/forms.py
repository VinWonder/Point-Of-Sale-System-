from django import forms
from .models import Product, SupplierPurchase, Category, Supplier


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ('sku', 'name', 'category', 'unit', 'cost_price', 'sell_price', 'reorder_level', 'is_active')


class SupplierPurchaseForm(forms.ModelForm):
    class Meta:
        model = SupplierPurchase
        fields = ('supplier', 'product', 'branch', 'quantity', 'cost_price', 'is_paid')
