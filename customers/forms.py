from django import forms
from .models import Customer, DebtPayment


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = (
            'name', 'customer_type', 'phone_number', 'email', 'kra_pin', 'address',
            'credit_limit', 'notes', 'is_active',
        )
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Only owners/managers decide how much credit a customer gets.
        if user is not None and user.role == 'CASHIER':
            self.fields['credit_limit'].disabled = True

    def clean_phone_number(self):
        from payments.mpesa import InvalidPhoneNumber, normalize_phone
        raw = self.cleaned_data['phone_number']
        try:
            return normalize_phone(raw)
        except InvalidPhoneNumber:
            # Landlines and non-Safaricom numbers are still valid contacts.
            return raw.strip()


class DebtPaymentForm(forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    method = forms.ChoiceField(choices=DebtPayment.Method.choices, initial=DebtPayment.Method.CASH)
    reference = forms.CharField(max_length=100, required=False)
