from django import forms

from .models import ShopSettings


class ShopSettingsForm(forms.ModelForm):
    class Meta:
        model = ShopSettings
        fields = (
            'business_name', 'tagline', 'kra_pin', 'phone_number', 'email', 'address',
            'vat_rate', 'receipt_footer', 'max_cashier_discount_percent',
            'quotation_validity_days', 'require_open_shift',
        )

    def clean_vat_rate(self):
        rate = self.cleaned_data['vat_rate']
        if not 0 <= rate <= 50:
            raise forms.ValidationError('VAT rate must be between 0 and 50%.')
        return rate

    def clean_max_cashier_discount_percent(self):
        value = self.cleaned_data['max_cashier_discount_percent']
        if not 0 <= value <= 100:
            raise forms.ValidationError('Enter a percentage between 0 and 100.')
        return value
