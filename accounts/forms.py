from django import forms
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm

from branches.models import Branch
from .models import User


def limit_for_actor(form, actor):
    """
    Managers may only manage cashiers at their own branch; only owners can
    create managers or other owners.
    """
    if actor is None or actor.role == User.Role.OWNER:
        form.fields['branch'].queryset = Branch.objects.filter(is_active=True)
        return
    form.fields['role'].choices = [(User.Role.CASHIER, User.Role.CASHIER.label)]
    form.fields['branch'].queryset = Branch.objects.filter(pk=actor.branch_id)
    form.fields['branch'].empty_label = None


class StaffCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'role', 'branch', 'phone_number')

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        limit_for_actor(self, actor)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('role') != User.Role.OWNER and not cleaned.get('branch'):
            self.add_error('branch', 'Managers and cashiers must belong to a branch.')
        return cleaned


class StaffEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'role', 'branch', 'phone_number', 'is_active')

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        limit_for_actor(self, actor)
        if actor is not None and actor.pk == self.instance.pk:
            # Nobody can demote or lock out themselves by accident.
            self.fields['role'].disabled = True
            self.fields['is_active'].disabled = True

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('role') != User.Role.OWNER and not cleaned.get('branch'):
            self.add_error('branch', 'Managers and cashiers must belong to a branch.')
        return cleaned


class StaffPasswordForm(SetPasswordForm):
    """Owner/manager sets a new password for a staff member who forgot theirs."""
