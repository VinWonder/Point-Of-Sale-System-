from django import forms
from .models import Branch, StockTransfer


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ('name', 'location', 'phone_number', 'is_active')


class StockTransferForm(forms.ModelForm):
    class Meta:
        model = StockTransfer
        fields = ('product', 'from_branch', 'to_branch', 'quantity', 'note')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['from_branch'].queryset = Branch.objects.filter(is_active=True)
        self.fields['to_branch'].queryset = Branch.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('from_branch') and cleaned.get('from_branch') == cleaned.get('to_branch'):
            raise forms.ValidationError('Source and destination branch must be different.')
        if cleaned.get('quantity') is not None and cleaned['quantity'] <= 0:
            self.add_error('quantity', 'Quantity must be at least 1.')
        return cleaned
