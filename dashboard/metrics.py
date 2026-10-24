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
    rows = (
        items.values('product_id', 'product__name', 'product__unit')
        .annotate(qty=Sum(F('quantity') - F('returned_quantity')), revenue=Sum(line_value), profit=Sum(line_profit))
        .filter(qty__gt=0)
        .order_by(f'-{order}')
    )
    return list(rows[:limit] if limit else rows)


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


PERIODS = {
    'today': 'Today',
    '7d': 'Last 7 days',
    '30d': 'Last 30 days',
    'month': 'This month',
}


def period_range(key, today):
    """
    (start, end, previous_start, previous_end) for a dashboard period. The
    previous range has the same length and ends the day before `start`, so
    deltas compare like with like (this month so far vs the same days last month).
    """
    if key == '7d':
        start = today - timedelta(days=6)
    elif key == '30d':
        start = today - timedelta(days=29)
    elif key == 'month':
        start = today.replace(day=1)
    else:
        start = today
    length = (today - start).days
    if key == 'month':
        prev_end = start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        prev_end = min(prev_start + timedelta(days=length), prev_end)
    else:
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length)
    return start, today, prev_start, prev_end


def collected(start, end, branch=None):
    """Money actually received in the range, by method (sale payments + debt repayments)."""
    from customers.models import DebtPayment
    from payments.models import Payment

    payments = Payment.objects.filter(status=Payment.Status.SUCCESS, debt_payment__isnull=True).exclude(
        method=Payment.Method.CREDIT_NOTE)
    payments = _between(payments, start, end)
    debts = _between(DebtPayment.objects.all(), start, end)
    if branch:
        payments = payments.filter(sale__branch=branch)
        debts = debts.filter(branch=branch)
    by_method = {}
    for qs in (payments, debts):
        for row in qs.values('method').annotate(t=Sum('amount')):
            by_method[row['method']] = by_method.get(row['method'], Decimal('0')) + row['t']
    return by_method


def hourly_series(day, branch=None):
    """Revenue for each opening hour (06:00-21:00) of one day, in shop time."""
    from django.db.models.functions import ExtractHour

    rows = (
        live_sales(branch).filter(created_at__date=day)
        .annotate(h=ExtractHour('created_at')).values('h').annotate(revenue=Sum('total'), count=Count('id'))
    )
    by_hour = {r['h']: r for r in rows}
    return [
        {'hour': h, 'revenue': float(by_hour.get(h, {}).get('revenue') or 0), 'count': by_hour.get(h, {}).get('count') or 0}
        for h in range(6, 22)
    ]


def busiest_hours(start, end, branch=None):
    """Average sales count per hour of day across the range — when to have more staff on the counter."""
    from django.db.models.functions import ExtractHour

    rows = (
        _between(live_sales(branch), start, end)
        .annotate(h=ExtractHour('created_at')).values('h').annotate(count=Count('id'))
    )
    by_hour = {r['h']: r['count'] for r in rows}
    return [{'hour': h, 'count': by_hour.get(h, 0)} for h in range(6, 22)]


def category_sales(start, end, branch=None, limit=6):
    items = SaleItem.objects.filter(sale__in=_between(live_sales(branch), start, end))
    value = ExpressionWrapper(
        (F('quantity') - F('returned_quantity')) * F('unit_price'),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    rows = list(
        items.values('product__category__name').annotate(revenue=Sum(value)).filter(revenue__gt=0).order_by('-revenue')
    )
    head, tail = rows[:limit], rows[limit:]
    result = [{'name': r['product__category__name'] or 'Uncategorised', 'revenue': float(r['revenue'])} for r in head]
    if tail:
        result.append({'name': 'Other', 'revenue': float(sum(r['revenue'] for r in tail))})
    return result


def stock_health(branch=None):
    from inventory.models import Stock

    stocks = Stock.objects.filter(product__is_active=True)
    if branch:
        stocks = stocks.filter(branch=branch)
    out = stocks.filter(quantity__lte=0).count()
    low = stocks.filter(quantity__gt=0, quantity__lte=F('product__reorder_level')).count()
    total = stocks.count()
    return {'out': out, 'low': low, 'ok': total - out - low, 'total': total}
