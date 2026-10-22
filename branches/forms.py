from django import forms
from .models import Branch, StockTransfer


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ('name', 'location', 'phone_number', 'is_active')


class StockTransferForm(forms.ModelForm):
    class Meta:
        model = StockTransfer
        fields = ('product', 'from_branch', 'to_branch', 'quantity')
