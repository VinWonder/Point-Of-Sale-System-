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


@register.simple_tag
def sparkline(values, width=120, height=32, stroke='currentColor'):
    """Tiny inline SVG trend line for KPI cards (no JavaScript needed)."""
    from django.utils.safestring import mark_safe

    values = [float(v or 0) for v in values or []]
    if len(values) < 2:
        return ''
    top = max(values) or 1
    step = width / (len(values) - 1)
    points = ' '.join(
        f'{i * step:.1f},{height - 2 - (v / top) * (height - 4):.1f}' for i, v in enumerate(values)
    )
    last_x, last_y = points.split(' ')[-1].split(',')
    return mark_safe(
        f'<svg class="sparkline" viewBox="0 0 {width} {height}" width="{width}" height="{height}" aria-hidden="true">'
        f'<polyline fill="none" stroke="{stroke}" stroke-width="2" stroke-linejoin="round" '
        f'stroke-linecap="round" points="{points}"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="3" fill="{stroke}"/></svg>'
    )
