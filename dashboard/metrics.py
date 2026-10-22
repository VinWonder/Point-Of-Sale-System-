"""
Business numbers computed in the database. Every function takes an optional
`branch` so owners can look at one shop or the whole business.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce, TruncDate

from sales.models import Sale, SaleItem, SaleReturn

ZERO = Value(Decimal('0.00'), output_field=DecimalField(max_digits=14, decimal_places=2))


def live_sales(branch=None):
    qs = Sale.objects.exclude(status=Sale.Status.VOIDED)
    return qs.filter(branch=branch) if branch else qs


def _between(qs, start, end, field='created_at'):
    if start:
        qs = qs.filter(**{f'{field}__date__gte': start})
    if end:
        qs = qs.filter(**{f'{field}__date__lte': end})
    return qs


def sales_totals(start, end, branch=None):
    """Revenue (net of refunds), cost of goods sold, gross profit, counts."""
    sales = _between(live_sales(branch), start, end)
    agg = sales.aggregate(
        revenue=Coalesce(Sum('total'), ZERO),
        discount=Coalesce(Sum('discount_amount'), ZERO),
        vat=Coalesce(Sum('tax_amount'), ZERO),
        collected=Coalesce(Sum('amount_paid'), ZERO),
        count=Count('id'),
    )
    returns = _between(SaleReturn.objects.filter(sale__in=sales), start, end)
    refunds = returns.aggregate(s=Coalesce(Sum('refund_amount'), ZERO))['s']

    cost = SaleItem.objects.filter(sale__in=sales).aggregate(
        cost=Coalesce(Sum(ExpressionWrapper(
            (F('quantity') - F('returned_quantity')) * F('cost_price'),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )), ZERO),
    )['cost']

    net = agg['revenue'] - refunds
    agg.update({
        'refunds': refunds,
        'net_revenue': net,
        'cost': cost,
        'gross_profit': net - cost,
        'margin': round(float((net - cost) / net * 100), 1) if net else 0.0,
        'average_sale': (agg['revenue'] / agg['count']).quantize(Decimal('0.01')) if agg['count'] else Decimal('0.00'),
    })
    return agg


def daily_series(start, end, branch=None):
    """Revenue per day between start and end (inclusive), zero-filled."""
    rows = (
        _between(live_sales(branch), start, end)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(revenue=Sum('total'), count=Count('id'))
    )
    by_day = {r['day']: r for r in rows}
    days, day = [], start
    while day <= end:
        r = by_day.get(day, {})
        days.append({'day': day, 'revenue': float(r.get('revenue') or 0), 'count': r.get('count') or 0})
        day += timedelta(days=1)
    return days


def payment_mix(start, end, branch=None):
    from payments.models import Payment
    payments = Payment.objects.filter(status=Payment.Status.SUCCESS, sale__in=_between(live_sales(branch), start, end))
    labels = dict(Payment.Method.choices)
    rows = payments.values('method').annotate(total=Sum('amount')).order_by('-total')
    return [{'method': labels.get(r['method'], r['method']), 'total': float(r['total'])} for r in rows]


def top_products(start, end, branch=None, limit=10, order='revenue'):
    items = SaleItem.objects.filter(sale__in=_between(live_sales(branch), start, end))
    line_value = ExpressionWrapper(
        (F('quantity') - F('returned_quantity')) * F('unit_price'),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    line_profit = ExpressionWrapper(
        (F('quantity') - F('returned_quantity')) * (F('unit_price') - F('cost_price')),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    return list(
        items.values('product_id', 'product__name', 'product__unit')
        .annotate(qty=Sum(F('quantity') - F('returned_quantity')), revenue=Sum(line_value), profit=Sum(line_profit))
        .filter(qty__gt=0)
        .order_by(f'-{order}')[:limit]
    )


def branch_comparison(start, end):
    return list(
        _between(live_sales(), start, end)
        .values('branch__name')
        .annotate(revenue=Sum('total'), count=Count('id'))
        .order_by('-revenue')
    )


def staff_performance(start, end, branch=None):
    return list(
        _between(live_sales(branch), start, end)
        .values('served_by__username', 'served_by__first_name', 'served_by__last_name')
        .annotate(revenue=Sum('total'), count=Count('id'), discounts=Sum('discount_amount'))
        .order_by('-revenue')
    )
