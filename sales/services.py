"""
Checkout business rules live here so the POS screen, quotation conversion
and tests all go through exactly the same checks.
"""
from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from accounts.audit import log_action
from accounts.models import User
from core.models import ShopSettings
from customers.models import Customer
from inventory.models import Product, StockMovement
from inventory.services import adjust_stock, InsufficientStock
from payments.models import Payment
from .models import Sale, SaleItem


PAYMENT_METHODS = ('CASH', 'MPESA', 'CARD', 'CREDIT')


class SaleError(Exception):
    """A checkout rule was broken. `status` is the HTTP status the API should return."""
    status = 400


class CustomerBlocked(SaleError):
    status = 403


def to_decimal(value, field='amount'):
    if value in (None, ''):
        return Decimal('0.00')
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SaleError(f'Invalid {field}.')
    if amount < 0 or not amount.is_finite():
        raise SaleError(f'{field.capitalize()} cannot be negative.')
    return amount.quantize(Decimal('0.01'))


def parse_lines(raw_items):
    """
    Turn [{'product_id': 1, 'qty': 2}, ...] into an ordered {product: qty}
    mapping, merging duplicate lines and rejecting bad quantities.
    """
    if not raw_items:
        raise SaleError('Cart is empty.')

    quantities = OrderedDict()
    for line in raw_items:
        try:
            product_id = int(line['product_id'])
            qty = int(line['qty'])
        except (KeyError, TypeError, ValueError):
            raise SaleError('Each cart line needs a product and a whole-number quantity.')
        if qty <= 0:
            raise SaleError('Quantities must be at least 1.')
        quantities[product_id] = quantities.get(product_id, 0) + qty

    products = Product.objects.in_bulk(quantities.keys())
    lines = OrderedDict()
    for product_id, qty in quantities.items():
        product = products.get(product_id)
        if product is None or not product.is_active:
            raise SaleError('One of the products in the cart is no longer available.')
        lines[product] = qty
    return lines


def check_customer_can_buy(customer):
    if customer and customer.is_defaulter:
        raise CustomerBlocked(
            f'{customer.name} owes KES {customer.balance_owed:,.2f} and has exceeded their credit '
            f'limit of KES {customer.credit_limit:,.2f}. Settle the outstanding balance before a new sale.'
        )


def check_discount_allowed(user, subtotal, discount, settings):
    if discount > subtotal:
        raise SaleError('Discount cannot be more than the sale value.')
    if discount and user.role == User.Role.CASHIER and subtotal:
        percent = discount / subtotal * 100
        if percent > settings.max_cashier_discount_percent:
            raise SaleError(
                f'Cashiers can give at most {settings.max_cashier_discount_percent}% discount. '
                f'Ask a manager to approve a bigger discount.'
            )


@transaction.atomic
def checkout(*, user, branch, raw_items=None, lines=None, customer=None, payment_method='CASH',
             discount=0, cash_tendered=None, notes='', quotation=None, prices=None,
             customer_name='', customer_phone=''):
    """
    Create a completed sale and move stock. Returns the Sale.

    `lines` ({product: qty}) may be given instead of `raw_items`. `prices`
    ({product_id: unit_price}) overrides normal pricing — used when a
    quotation is honoured at the price that was quoted.
    """
    if branch is None:
        raise SaleError('Your account is not assigned to a branch. Contact your manager.')
    if payment_method not in PAYMENT_METHODS:
        raise SaleError('Choose a valid payment method.')

    settings = ShopSettings.load()
    if lines is None:
        lines = parse_lines(raw_items)
    if not lines:
        raise SaleError('Cart is empty.')

    if customer is not None:
        # Lock the customer row so two tills can't both spend the same credit.
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
    check_customer_can_buy(customer)

    discount = to_decimal(discount, 'discount')
    prices = prices or {}
    priced_lines = [
        (product, qty, prices.get(product.pk, product.price_for_quantity(qty)))
        for product, qty in lines.items()
    ]
    subtotal = sum((qty * price for _, qty, price in priced_lines), Decimal('0.00'))
    check_discount_allowed(user, subtotal, discount, settings)
    total = subtotal - discount

    if payment_method == 'CREDIT':
        if customer is None:
            raise SaleError('A customer must be selected for credit/on-account sales.')
        if customer.balance_owed + total > customer.credit_limit:
            raise SaleError(
                f'This sale would take {customer.name} to KES {customer.balance_owed + total:,.2f}, '
                f'over their credit limit of KES {customer.credit_limit:,.2f} '
                f'(available credit: KES {customer.available_credit:,.2f}).'
            )

    tendered = None
    if payment_method == 'CASH' and cash_tendered not in (None, ''):
        tendered = to_decimal(cash_tendered, 'cash tendered')
        if tendered < total:
            raise SaleError(f'Cash tendered (KES {tendered:,.2f}) is less than the total (KES {total:,.2f}).')

    sale = Sale.objects.create(
        customer=customer, branch=branch, served_by=user, quotation=quotation,
        customer_name='' if customer else customer_name.strip()[:150],
        customer_phone='' if customer else customer_phone.strip()[:20],
        discount_amount=discount, cash_tendered=tendered, notes=notes[:255],
        sale_type=Sale.SaleType.CREDIT if payment_method == 'CREDIT' else Sale.SaleType.CASH,
        status=Sale.Status.PENDING_PAYMENT if payment_method == 'MPESA' else Sale.Status.COMPLETED,
    )
    for product, qty, price in priced_lines:
        SaleItem.objects.create(
            sale=sale, product=product, quantity=qty, unit_price=price, cost_price=product.cost_price,
        )
        try:
            adjust_stock(
                product, branch, -qty, StockMovement.Kind.SALE, user=user,
                reference=f'Receipt #{sale.pk}',
            )
        except InsufficientStock as exc:
            raise SaleError(str(exc))

    sale.recalculate_totals(settings.vat_rate)

    if payment_method in ('CASH', 'CARD'):
        Payment.objects.create(
            sale=sale, method=payment_method, amount=sale.total, status=Payment.Status.SUCCESS,
            received_by=user,
        )
        sale.refresh_payment_status()
    elif payment_method == 'CREDIT':
        customer.balance_owed += sale.total
        customer.save(update_fields=['balance_owed'])
    # MPESA: stays UNPAID/PENDING until the Safaricom callback confirms payment.

    sale.save()
    log_action(user, f'Sale #{sale.pk} ({payment_method}) KES {sale.total:,.2f}', sale)
    return sale


def mark_completed_if_paid(sale):
    """M-Pesa sales are held as 'awaiting payment' until fully paid."""
    if sale.status == Sale.Status.PENDING_PAYMENT and sale.payment_status == Sale.PaymentStatus.PAID:
        sale.status = Sale.Status.COMPLETED


@transaction.atomic
def void_sale(sale, user, reason):
    """
    Cancel a sale made in error: stock goes back on the shelf, any credit
    charged to the customer is reversed. Payments already taken must be
    refunded by hand and are flagged in the audit log.
    """
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status == Sale.Status.VOIDED:
        raise SaleError('This sale has already been voided.')
    if not reason.strip():
        raise SaleError('Give a reason for voiding the sale.')

    for item in sale.items.select_related('product'):
        remaining = item.quantity - item.returned_quantity
        if remaining:
            adjust_stock(
                item.product, sale.branch, remaining, StockMovement.Kind.VOID, user=user,
                reference=f'Receipt #{sale.pk}', note=reason[:255],
            )

    if sale.sale_type == Sale.SaleType.CREDIT and sale.customer_id:
        customer = Customer.objects.select_for_update().get(pk=sale.customer_id)
        outstanding = max(sale.total - sale.amount_paid, Decimal('0.00'))
        customer.balance_owed = max(customer.balance_owed - outstanding, Decimal('0.00'))
        customer.save(update_fields=['balance_owed'])

    sale.status = Sale.Status.VOIDED
    sale.voided_by = user
    sale.voided_at = timezone.now()
    sale.void_reason = reason[:255]
    sale.save(update_fields=['status', 'voided_by', 'voided_at', 'void_reason'])

    refund_note = f' Refund KES {sale.amount_paid:,.2f} to the customer.' if sale.amount_paid else ''
    log_action(user, f'Voided sale #{sale.pk}', sale, reason + refund_note)
    return sale


@transaction.atomic
def process_return(sale, user, quantities, reason, refund_method, restock=None):
    """
    Return goods from `sale`. `quantities` maps SaleItem id -> qty to return;
    `restock` maps SaleItem id -> bool (default True). The refund is the
    line value less the sale's discount share, so discounts aren't refunded twice.
    """
    from .models import SaleReturn, SaleReturnItem

    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status == Sale.Status.VOIDED:
        raise SaleError('This sale was voided; nothing can be returned.')
    if not reason.strip():
        raise SaleError('Give a reason for the return.')
    if refund_method not in SaleReturn.RefundMethod.values:
        raise SaleError('Choose how the customer is refunded.')
    if refund_method == SaleReturn.RefundMethod.ACCOUNT and not sale.customer_id:
        raise SaleError('Walk-in sales cannot be refunded to an account.')
    restock = restock or {}

    items = {item.pk: item for item in sale.items.select_for_update().select_related('product')}
    lines = []
    for item_id, qty in quantities.items():
        item = items.get(int(item_id))
        qty = int(qty or 0)
        if item is None or qty <= 0:
            continue
        if qty > item.returnable_quantity:
            raise SaleError(f'Only {item.returnable_quantity} of {item.product.name} can still be returned.')
        lines.append((item, qty))
    if not lines:
        raise SaleError('Select at least one item to return.')

    discount_ratio = (sale.total / sale.subtotal) if sale.subtotal else Decimal('1')
    refund_total = Decimal('0.00')
    sale_return = SaleReturn.objects.create(
        sale=sale, branch=sale.branch, refund_method=refund_method, refund_amount=0,
        reason=reason[:255], processed_by=user,
    )
    for item, qty in lines:
        amount = (qty * item.unit_price * discount_ratio).quantize(Decimal('0.01'))
        put_back = restock.get(item.pk, True)
        SaleReturnItem.objects.create(
            sale_return=sale_return, sale_item=item, quantity=qty, restock=put_back, amount=amount,
        )
        item.returned_quantity += qty
        item.save(update_fields=['returned_quantity'])
        if put_back:
            adjust_stock(
                item.product, sale.branch, qty, StockMovement.Kind.RETURN, user=user,
                reference=f'Return #{sale_return.pk} (Receipt #{sale.pk})', note=reason[:255],
            )
        refund_total += amount

    sale_return.refund_amount = refund_total
    sale_return.save(update_fields=['refund_amount'])
    if refund_method == SaleReturn.RefundMethod.ACCOUNT and refund_total > sale.balance_due:
        raise SaleError(
            f'Only KES {sale.balance_due:,.2f} is still owed on this sale. '
            f'Refund the KES {refund_total:,.2f} in cash or M-Pesa instead.'
        )

    if refund_method == SaleReturn.RefundMethod.ACCOUNT:
        # Returned goods first cancel what is still owed on this sale.
        customer = Customer.objects.select_for_update().get(pk=sale.customer_id)
        Payment.objects.create(
            sale=sale, method=Payment.Method.CREDIT_NOTE, amount=refund_total,
            status=Payment.Status.SUCCESS, reference=f'Return #{sale_return.pk}', received_by=user,
        )
        customer.balance_owed = max(customer.balance_owed - refund_total, Decimal('0.00'))
        customer.save(update_fields=['balance_owed'])
        sale.refresh_payment_status()
        sale.save(update_fields=['payment_status', 'amount_paid'])

    log_action(user, f'Return on sale #{sale.pk}: KES {refund_total:,.2f} ({refund_method})', sale_return, reason)
    return sale_return
