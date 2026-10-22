from django import forms
from .models import Product, SupplierPurchase, Category, Supplier


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            'sku', 'barcode', 'name', 'brand', 'category', 'unit', 'description',
            'cost_price', 'sell_price', 'wholesale_price', 'wholesale_min_qty',
            'reorder_level', 'is_active',
        )
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}

    def clean(self):
        cleaned = super().clean()
        cost, sell = cleaned.get('cost_price'), cleaned.get('sell_price')
        wholesale = cleaned.get('wholesale_price')
        if cost is not None and sell is not None and sell < cost:
            self.add_error('sell_price', 'Selling price is below cost — you would make a loss on every sale.')
        if wholesale is not None and sell is not None and wholesale > sell:
            self.add_error('wholesale_price', 'Wholesale price should not be higher than the retail price.')
        if wholesale and not cleaned.get('wholesale_min_qty'):
            self.add_error('wholesale_min_qty', 'Set the quantity at which the wholesale price applies.')
        return cleaned


class SupplierPurchaseForm(forms.ModelForm):
    class Meta:
        model = SupplierPurchase
        fields = ('supplier', 'product', 'branch', 'quantity', 'cost_price', 'is_paid')
