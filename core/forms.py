from django import forms

from .images import logo_to_data_uri
from .models import ShopSettings


class ShopSettingsForm(forms.ModelForm):
    logo_upload = forms.ImageField(
        required=False, label='Company logo',
        help_text='Optional. PNG or JPG, square works best. Shown on quotations, invoices and receipts.',
    )
    remove_logo = forms.BooleanField(required=False, label='Remove current logo')

    class Meta:
        model = ShopSettings
        fields = (
            'business_name', 'show_logo', 'tagline', 'kra_pin', 'phone_number', 'email', 'address',
            'vat_rate', 'receipt_footer', 'max_cashier_discount_percent',
            'quotation_validity_days', 'monthly_sales_target', 'require_open_shift',
            'mpesa_paybill', 'mpesa_paybill_account', 'mpesa_till',
            'bank_name', 'bank_account_name', 'bank_account_number', 'bank_branch',
            'invoice_due_days', 'invoice_terms',
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

    def clean_logo_upload(self):
        upload = self.cleaned_data.get('logo_upload')
        if upload:
            upload.seek(0)
            return logo_to_data_uri(upload)
        return None

    def save(self, commit=True):
        settings = super().save(commit=False)
        if self.cleaned_data.get('remove_logo'):
            settings.logo = ''
        elif self.cleaned_data.get('logo_upload'):
            settings.logo = self.cleaned_data['logo_upload']
        if commit:
            settings.save()
        return settings
