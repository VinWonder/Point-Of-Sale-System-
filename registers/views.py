from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.audit import log_action
from branches.models import Branch
from core.filters import PRESETS, date_range_from_request, filter_by_date
from core.utils import paginate
from .models import Expense, Shift
from .services import ShiftError, close_shift, current_shift, open_shift, shift_summary


def _amount(raw):
    try:
        return Decimal(str(raw or '0')).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        raise ShiftError('Enter a valid amount.')


def _can_view_shift(user, shift):
    if user.role == User.Role.OWNER:
        return True
    if user.role == User.Role.MANAGER:
        return shift.branch_id == user.branch_id
    return shift.cashier_id == user.id


@login_required
def my_shift(request):
    """Open a shift, or see the running totals of the one that is open."""
    shift = current_shift(request.user)
    if request.method == 'POST' and shift is None:
        try:
            open_shift(request.user, _amount(request.POST.get('opening_float')))
        except ShiftError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, 'Shift opened. Good selling!')
            return redirect('sales:pos')
    return render(request, 'registers/my_shift.html', {
        'shift': shift,
        'summary': shift_summary(shift) if shift else None,
    })


@login_required
@require_POST
def shift_close(request, shift_id):
    shift = get_object_or_404(Shift, pk=shift_id, status=Shift.Status.OPEN)
    if shift.cashier_id != request.user.id and request.user.role == User.Role.CASHIER:
        messages.error(request, 'You can only close your own shift.')
        return redirect('registers:my_shift')
    try:
        shift = close_shift(shift, request.user, _amount(request.POST.get('counted_cash')),
                            request.POST.get('notes', ''))
    except ShiftError as exc:
        messages.error(request, str(exc))
        return redirect('registers:my_shift')
    variance = shift.variance
    if variance == 0:
        messages.success(request, 'Shift closed. Cash balances exactly.')
    elif variance > 0:
        messages.warning(request, f'Shift closed. Cash is OVER by KES {variance:,.2f}.')
    else:
        messages.error(request, f'Shift closed. Cash is SHORT by KES {-variance:,.2f}.')
    return redirect('registers:shift_detail', shift_id=shift.id)


@login_required
def shift_detail(request, shift_id):
    """Z-report for one shift."""
    shift = get_object_or_404(Shift.objects.select_related('cashier', 'branch'), pk=shift_id)
    if not _can_view_shift(request.user, shift):
        messages.error(request, 'You cannot view that shift.')
        return redirect('registers:my_shift')
    return render(request, 'registers/shift_detail.html', {'shift': shift, 'summary': shift_summary(shift)})


@login_required
def shift_list(request):
    shifts = Shift.objects.select_related('cashier', 'branch')
    if request.user.role == User.Role.CASHIER:
        shifts = shifts.filter(cashier=request.user)
    elif request.user.role == User.Role.MANAGER:
        shifts = shifts.filter(branch_id=request.user.branch_id)
    start, end, preset = date_range_from_request(request, default='month')
    shifts = filter_by_date(shifts, start, end, field='opened_at')
    return render(request, 'registers/shift_list.html', {
        'page_obj': paginate(request, shifts),
        'start': start, 'end': end, 'preset': preset, 'date_presets': PRESETS,
    })


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ('category', 'description', 'amount', 'paid_from_till', 'reference')

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Amount must be more than zero.')
        return amount


@login_required
def expense_list(request):
    expenses = Expense.objects.select_related('branch', 'recorded_by')
    if request.user.role != User.Role.OWNER:
        expenses = expenses.filter(branch_id=request.user.branch_id)
    else:
        branch = request.GET.get('branch', '')
        if branch.isdigit():
            expenses = expenses.filter(branch_id=branch)
    start, end, preset = date_range_from_request(request, default='month')
    expenses = filter_by_date(expenses, start, end)
    category = request.GET.get('category', '')
    if category in Expense.Category.values:
        expenses = expenses.filter(category=category)

    form = ExpenseForm(request.POST or None)
    if request.method == 'POST':
        if not request.user.branch_id:
            messages.error(request, 'Your account is not assigned to a branch.')
        elif form.is_valid():
            expense = form.save(commit=False)
            expense.branch = request.user.branch
            expense.recorded_by = request.user
            expense.save()
            log_action(request.user, f'Recorded expense KES {expense.amount:,.2f}', expense, expense.description)
            messages.success(request, 'Expense recorded.')
            return redirect('registers:expense_list')

    by_category = expenses.values('category').annotate(total=Sum('amount')).order_by('-total')
    labels = dict(Expense.Category.choices)
    return render(request, 'registers/expense_list.html', {
        'page_obj': paginate(request, expenses),
        'form': form,
        'total': expenses.aggregate(s=Sum('amount'))['s'] or Decimal('0.00'),
        'by_category': [{'label': labels[r['category']], 'total': r['total']} for r in by_category],
        'categories': Expense.Category.choices,
        'current_category': category,
        'branches': Branch.objects.order_by('name'),
        'start': start, 'end': end, 'preset': preset, 'date_presets': PRESETS,
    })
