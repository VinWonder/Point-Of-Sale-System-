"""
Creating and editing quotations. Prices can be negotiated at the counter,
but within limits: cashiers only down to the shop's discount cap, managers
not below cost, owners freely.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from accounts.audit import log_action
from accounts.models import User
from core.models import ShopSettings
from inventory.models import Product
from .models import Quotation, QuotationItem
from .services import SaleError

MAX_VALID_DAYS = 90


def _price(raw):
    try:
        price = Decimal(str(raw)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        raise SaleError('Enter a valid unit price.')
    if not price.is_finite() or price <= 0:
        raise SaleError('Unit prices must be more than zero.')
    return price


def check_price_allowed(user, product, qty, price, settings):
    """Refuse negotiated prices beyond what the user's role may approve."""
    list_price = product.price_for_quantity(qty)
    if price >= list_price or user.role == User.Role.OWNER:
        return
    if user.role == User.Role.MANAGER:
        if price < product.cost_price:
            raise SaleError(f'{product.name}: KES {price:,.2f} is below cost. Only the owner can approve that.')
        return
    floor = (list_price * (100 - settings.max_cashier_discount_percent) / 100).quantize(Decimal('0.01'))
    if price < floor:
        raise SaleError(
            f'{product.name}: lowest price you can give is KES {floor:,.2f} '
            f'({settings.max_cashier_discount_percent}% off). Ask a manager for a lower price.'
        )


def parse_quote_lines(user, raw_items, settings):
    """[{'product_id', 'qty', 'unit_price'?}] -> [(product, qty, price)], merging repeated products."""
    if not raw_items:
        raise SaleError('Add at least one item to the quotation.')
    merged = {}
    for line in raw_items:
        try:
            product_id, qty = int(line['product_id']), int(line['qty'])
        except (KeyError, TypeError, ValueError):
            raise SaleError('Each line needs an item from the system and a whole-number quantity.')
        if qty <= 0:
            raise SaleError('Quantities must be at least 1.')
        if product_id in merged:
            merged[product_id]['qty'] += qty
        else:
            merged[product_id] = {'qty': qty, 'price': line.get('unit_price')}

    products = Product.objects.in_bulk(merged.keys())
    lines = []
    for product_id, entry in merged.items():
        product = products.get(product_id)
        if product is None or not product.is_active:
            raise SaleError('One of the items is no longer sold. Remove it and try again.')
        qty = entry['qty']
        if entry['price'] in (None, ''):
            price = product.price_for_quantity(qty)
        else:
            price = _price(entry['price'])
            check_price_allowed(user, product, qty, price, settings)
        lines.append((product, qty, price))
    return lines


@transaction.atomic
def save_quotation(*, user, raw_items, customer=None, customer_name='', customer_phone='',
                   valid_days=None, notes='', quotation=None):
    """Create a new quotation, or replace the contents of an open one (keeping its number)."""
    if not user.branch_id and quotation is None:
        raise SaleError('Your account is not assigned to a branch. Contact your manager.')
    settings = ShopSettings.load()
    lines = parse_quote_lines(user, raw_items, settings)

    try:
        valid_days = int(valid_days) if valid_days not in (None, '') else settings.quotation_validity_days
    except (TypeError, ValueError):
        raise SaleError('Validity must be a number of days.')
    if not 1 <= valid_days <= MAX_VALID_DAYS:
        raise SaleError(f'Validity must be between 1 and {MAX_VALID_DAYS} days.')

    fields = {
        'customer': customer,
        'customer_name': '' if customer else (customer_name or '').strip()[:150],
        'customer_phone': '' if customer else (customer_phone or '').strip()[:20],
        'notes': (notes or '').strip()[:255],
    }
    if quotation is None:
        quotation = Quotation.objects.create(
            branch=user.branch, created_by=user,
            valid_until=timezone.localdate() + timedelta(days=valid_days), **fields,
        )
        action = 'Created'
    else:
        quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
        if quotation.status != Quotation.Status.DRAFT:
            raise SaleError('Only open quotations can be edited.')
        for key, value in fields.items():
            setattr(quotation, key, value)
        quotation.valid_until = timezone.localdate() + timedelta(days=valid_days)
        quotation.save()
        quotation.items.all().delete()
        action = 'Edited'

    QuotationItem.objects.bulk_create([
        QuotationItem(quotation=quotation, product=product, quantity=qty, unit_price=price)
        for product, qty, price in lines
    ])
    log_action(user, f'{action} quotation {quotation.reference}', quotation,
               f'{len(lines)} item(s), KES {quotation.total:,.2f}')
    return quotation
