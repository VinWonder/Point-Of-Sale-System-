from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import User


class StaffCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'role', 'branch', 'phone_number')


class StaffEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'role', 'branch', 'phone_number', 'is_active')
