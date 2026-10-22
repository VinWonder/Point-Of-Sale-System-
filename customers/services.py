from decimal import Decimal

from django.db import transaction

from accounts.audit import log_action
from .models import Customer, DebtPayment


class DebtPaymentError(Exception):
    pass


@transaction.atomic
def record_debt_payment(customer, amount, user, method=DebtPayment.Method.CASH, reference=''):
    """
    Reduce what a customer owes, then settle their oldest unpaid credit
    sales first so each receipt shows its true remaining balance.
    """
    from payments.models import Payment
    from sales.models import Sale

    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    amount = Decimal(amount)
    if amount <= 0:
        raise DebtPaymentError('Amount must be more than zero.')
    if amount > customer.balance_owed:
        raise DebtPaymentError(
            f'{customer.name} only owes KES {customer.balance_owed:,.2f}. '
            f'You entered KES {amount:,.2f}.'
        )

    customer.balance_owed -= amount
    customer.save(update_fields=['balance_owed'])
    debt_payment = DebtPayment.objects.create(
        customer=customer, amount=amount, method=method, reference=reference,
        balance_after=customer.balance_owed, branch=getattr(user, 'branch', None), received_by=user,
    )

    remaining = amount
    open_sales = (
        Sale.objects.select_for_update()
        .filter(customer=customer, sale_type=Sale.SaleType.CREDIT)
        .exclude(status=Sale.Status.VOIDED)
        .exclude(payment_status=Sale.PaymentStatus.PAID)
        .order_by('created_at')
    )
    payment_method = method if method in Payment.Method.values else Payment.Method.CASH
    for sale in open_sales:
        if remaining <= 0:
            break
        portion = min(sale.balance_due, remaining)
        if portion <= 0:
            continue
        Payment.objects.create(
            sale=sale, method=payment_method, amount=portion, status=Payment.Status.SUCCESS,
            reference=reference or f'Debt payment #{debt_payment.pk}', received_by=user,
            debt_payment=debt_payment,
        )
        sale.refresh_payment_status()
        sale.save(update_fields=['payment_status', 'amount_paid'])
        remaining -= portion

    log_action(user, f'Debt payment KES {amount:,.2f} from {customer.name}', debt_payment)
    return debt_payment
