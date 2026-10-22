from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.audit import log_action
from .models import Expense, Shift


class ShiftError(Exception):
    pass


def current_shift(user):
    return Shift.objects.filter(cashier=user, status=Shift.Status.OPEN).first()


def _total(queryset, field='amount'):
    return queryset.aggregate(s=Sum(field))['s'] or Decimal('0.00')


def shift_summary(shift, until=None):
    """
    Money that passed through this cashier's hands during the shift,
    broken down by method, and the cash that should be in the drawer.
    """
    from customers.models import DebtPayment
    from payments.models import Payment
    from sales.models import Sale, SaleReturn

    end = until or shift.closed_at or timezone.now()
    window = {'created_at__gte': shift.opened_at, 'created_at__lte': end}

    sale_payments = Payment.objects.filter(
        status=Payment.Status.SUCCESS, received_by=shift.cashier, debt_payment__isnull=True, **window,
    ).exclude(method=Payment.Method.CREDIT_NOTE)
    by_method = {
        row['method']: row['total']
        for row in sale_payments.values('method').annotate(total=Sum('amount'))
    }
    debt = DebtPayment.objects.filter(received_by=shift.cashier, **window)
    debt_by_method = {row['method']: row['total'] for row in debt.values('method').annotate(total=Sum('amount'))}

    sales = Sale.objects.filter(served_by=shift.cashier, **window)
    live_sales = sales.exclude(status=Sale.Status.VOIDED)
    cash_refunds = _total(SaleReturn.objects.filter(
        processed_by=shift.cashier, refund_method=SaleReturn.RefundMethod.CASH, **window,
    ), 'refund_amount')
    till_expenses = _total(Expense.objects.filter(recorded_by=shift.cashier, paid_from_till=True, **window))

    cash_in = by_method.get('CASH', Decimal('0.00')) + debt_by_method.get('CASH', Decimal('0.00'))
    expected = shift.opening_float + cash_in - cash_refunds - till_expenses
    return {
        'sales_count': live_sales.count(),
        'sales_total': _total(live_sales, 'total'),
        'voided_count': sales.filter(status=Sale.Status.VOIDED).count(),
        'credit_sales': _total(live_sales.filter(sale_type=Sale.SaleType.CREDIT), 'total'),
        'by_method': by_method,
        'debt_by_method': debt_by_method,
        'cash_in': cash_in,
        'cash_refunds': cash_refunds,
        'till_expenses': till_expenses,
        'opening_float': shift.opening_float,
        'expected_cash': expected,
    }


def open_shift(user, opening_float):
    if not user.branch_id:
        raise ShiftError('Your account is not assigned to a branch.')
    if current_shift(user):
        raise ShiftError('You already have an open shift. Close it first.')
    if opening_float < 0:
        raise ShiftError('Opening float cannot be negative.')
    shift = Shift.objects.create(branch=user.branch, cashier=user, opening_float=opening_float)
    log_action(user, f'Opened shift #{shift.pk} with float KES {opening_float:,.2f}', shift)
    return shift


@transaction.atomic
def close_shift(shift, user, counted_cash, notes=''):
    shift = Shift.objects.select_for_update().get(pk=shift.pk)
    if shift.status != Shift.Status.OPEN:
        raise ShiftError('This shift is already closed.')
    if counted_cash < 0:
        raise ShiftError('Counted cash cannot be negative.')
    now = timezone.now()
    shift.expected_cash = shift_summary(shift, until=now)['expected_cash']
    shift.counted_cash = counted_cash
    shift.closed_at = now
    shift.closing_notes = notes[:255]
    shift.status = Shift.Status.CLOSED
    shift.save()
    log_action(
        user, f'Closed shift #{shift.pk}: expected {shift.expected_cash:,.2f}, counted {counted_cash:,.2f}',
        shift, f'Variance {shift.variance:+,.2f}',
    )
    return shift
