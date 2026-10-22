from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value, currency='KES'):
    """Format a number as currency with thousands separators: 12500 -> 'KES 12,500.00'."""
    try:
        amount = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = '-' if amount < 0 else ''
    return f"{sign}{currency} {abs(amount):,.2f}"


@register.filter
def intcomma_plain(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return value
