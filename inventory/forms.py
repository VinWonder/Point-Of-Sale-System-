from django import forms
from .models import Product, SupplierPurchase, Category, Supplier


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name',)


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ('name', 'contact_person', 'phone_number', 'email', 'kra_pin', 'address', 'is_active')


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
        fields = ('supplier', 'invoice_number', 'product', 'branch', 'quantity', 'cost_price', 'is_paid')
        labels = {'cost_price': 'Unit cost price', 'is_paid': 'Already paid to supplier'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].queryset = Supplier.objects.filter(is_active=True)
        self.fields['product'].queryset = Product.objects.filter(is_active=True)

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        if quantity <= 0:
            raise forms.ValidationError('Quantity must be at least 1.')
        return quantity


class StockAdjustmentForm(forms.Form):
    """Correct stock for damage, theft, or after a physical count."""

    MODE_SET = 'set'
    MODE_CHANGE = 'change'
    REASONS = [
        ('Stock count correction', 'Stock count correction'),
        ('Damaged', 'Damaged / broken'),
        ('Lost or stolen', 'Lost or stolen'),
        ('Expired', 'Expired (cement, paint, adhesives)'),
        ('Found stock', 'Found stock'),
        ('Own use', 'Taken for shop use'),
        ('Other', 'Other'),
    ]

    product = forms.ModelChoiceField(queryset=Product.objects.filter(is_active=True))
    branch = forms.ModelChoiceField(queryset=None)
    mode = forms.ChoiceField(
        choices=[(MODE_SET, 'Set to counted quantity'), (MODE_CHANGE, 'Add / remove quantity')],
        widget=forms.RadioSelect, initial=MODE_SET,
    )
    quantity = forms.IntegerField(help_text='Counted quantity, or the change (use a minus sign to remove).')
    reason = forms.ChoiceField(choices=REASONS)
    note = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        from branches.models import Branch
        super().__init__(*args, **kwargs)
        self.fields['branch'].queryset = Branch.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        mode, qty = cleaned.get('mode'), cleaned.get('quantity')
        if qty is None:
            return cleaned
        if mode == self.MODE_SET and qty < 0:
            self.add_error('quantity', 'A counted quantity cannot be negative.')
        if mode == self.MODE_CHANGE and qty == 0:
            self.add_error('quantity', 'Enter a non-zero change.')
        return cleaned
