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


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    """Current querystring with some keys replaced — keeps filters when paging."""
    query = context['request'].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ''):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


@register.filter
def in_words(value):
    """12550 -> 'Kenya Shillings Twelve Thousand Five Hundred and Fifty Only'."""
    from core.words import amount_in_words
    try:
        return amount_in_words(value)
    except (InvalidOperation, TypeError, ValueError):
        return ''
