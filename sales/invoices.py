"""
Invoices. An invoice is a sale with a formal INV number and a due date:
goods leave the shop (stock is deducted) and the customer pays now or by
the due date. Quotations are only offers; invoices are what is owed.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.audit import log_action
from core.models import ShopSettings
from .models import Sale, next_invoice_number
from .quotations import parse_quote_lines
from .services import SaleError, checkout

MAX_DUE_DAYS = 120


def _due_days(raw, settings, sale_type):
    if sale_type != Sale.SaleType.CREDIT:
        return 0   # paid on the spot: due today
    if raw in (None, ''):
        return settings.invoice_due_days
    try:
        days = int(raw)
    except (TypeError, ValueError):
        raise SaleError('Payment terms must be a number of days.')
    if not 0 <= days <= MAX_DUE_DAYS:
        raise SaleError(f'Payment terms must be between 0 and {MAX_DUE_DAYS} days.')
    return days


@transaction.atomic
def issue_invoice(sale, due_days=None):
    """Give an existing sale an INV number (once) and a due date."""
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status == Sale.Status.VOIDED:
        raise SaleError('A voided sale cannot be invoiced.')
    if sale.invoice_number:
        return sale
    settings = ShopSettings.load()
    days = _due_days(due_days, settings, sale.sale_type)
    sale.invoice_number = next_invoice_number()
    sale.due_date = timezone.localtime(sale.created_at).date() + timedelta(days=days)
    sale.save(update_fields=['invoice_number', 'due_date'])
    return sale


@transaction.atomic
def create_invoice(*, user, raw_items, payment_method, customer=None, customer_name='', customer_phone='',
                   due_days=None, notes='', cash_tendered=None, quotation=None):
    """Create an invoice from the Invoice Desk: validate prices, sell, number it."""
    settings = ShopSettings.load()
    priced = parse_quote_lines(user, raw_items, settings)
    if payment_method == 'CREDIT' and customer is None:
        raise SaleError('Invoices on account need a registered customer. Register them first.')
    sale_type = Sale.SaleType.CREDIT if payment_method == 'CREDIT' else Sale.SaleType.CASH
    days = _due_days(due_days, settings, sale_type)

    sale = checkout(
        user=user, branch=user.branch,
        lines={product: qty for product, qty, _ in priced},
        prices={product.pk: price for product, _, price in priced},
        customer=customer, payment_method=payment_method, cash_tendered=cash_tendered,
        notes=notes, quotation=quotation, customer_name=customer_name, customer_phone=customer_phone,
    )
    sale = issue_invoice(sale, due_days=days)
    log_action(user, f'Issued invoice {sale.invoice_reference} ({payment_method})', sale,
               f'KES {sale.total:,.2f}, due {sale.due_date:%d/%m/%Y}')
    return sale
