from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import User
from branches.models import Branch
from core.exports import csv_response
from core.filters import PRESETS, date_range_from_request, filter_by_date
from registers.models import Expense, Shift
from sales.models import Sale
from . import metrics
from .views import scoped_branch

MANAGERS = (User.Role.OWNER, User.Role.MANAGER)


def report_context(request, default='month'):
    start, end, preset = date_range_from_request(request, default=default)
    return {
        'start': start, 'end': end, 'preset': preset, 'date_presets': PRESETS,
        'branch': scoped_branch(request),
        'branches': Branch.objects.filter(is_active=True).order_by('name'),
    }


REPORTS = [
    {'url': 'reports:profit_and_loss', 'icon': 'bi-calculator', 'title': 'Profit & Loss',
     'text': 'Revenue, refunds, cost of goods, gross profit, expenses and net profit for any period.'},
    {'url': 'reports:product_sales', 'icon': 'bi-box-seam', 'title': 'Product sales',
     'text': 'Units, revenue and profit per product and category. Find best sellers and slow movers.'},
    {'url': 'reports:staff_performance', 'icon': 'bi-person-badge', 'title': 'Staff performance',
     'text': 'Sales, value, discounts given and voids per cashier, plus cash-up variances.'},
]


@role_required(*MANAGERS)
def report_index(request):
    return render(request, 'reports/index.html', {'reports': REPORTS})


@role_required(*MANAGERS)
def profit_and_loss(request):
    ctx = report_context(request)
    start, end, branch = ctx['start'], ctx['end'], ctx['branch']
    totals = metrics.sales_totals(start, end, branch)

    expenses = filter_by_date(Expense.objects.all(), start, end)
    if branch:
        expenses = expenses.filter(branch=branch)
    labels = dict(Expense.Category.choices)
    expense_rows = [
        {'label': labels[r['category']], 'total': r['total']}
        for r in expenses.values('category').annotate(total=Sum('amount')).order_by('-total')
    ]
    expense_total = sum((r['total'] for r in expense_rows), Decimal('0.00'))

    ctx.update({
        'totals': totals,
        'expense_rows': expense_rows,
        'expense_total': expense_total,
        'net_profit': totals['gross_profit'] - expense_total,
        'uncollected': totals['revenue'] - totals['collected'],
    })
    return render(request, 'reports/profit_and_loss.html', ctx)


@role_required(*MANAGERS)
def product_sales(request):
    ctx = report_context(request)
    start, end, branch = ctx['start'], ctx['end'], ctx['branch']
    order = request.GET.get('order', 'revenue')
    if order not in ('revenue', 'qty', 'profit'):
        order = 'revenue'
    rows = metrics.top_products(start, end, branch, limit=None, order=order)
    for r in rows:
        r['margin'] = round(float(r['profit'] / r['revenue'] * 100), 1) if r['revenue'] else 0.0

    if request.GET.get('export') == 'csv':
        return csv_response('product-sales', ['Product', 'Unit', 'Qty sold', 'Revenue', 'Gross profit', 'Margin %'], (
            [r['product__name'], r['product__unit'], r['qty'], r['revenue'], r['profit'], r['margin']] for r in rows
        ))

    items = metrics.SaleItem.objects.filter(sale__in=metrics._between(metrics.live_sales(branch), start, end))
    by_category = (
        items.values('product__category__name')
        .annotate(revenue=Sum(ExpressionWrapper(
            (F('quantity') - F('returned_quantity')) * F('unit_price'),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )))
        .order_by('-revenue')
    )
    ctx.update({'rows': rows, 'order': order, 'by_category': by_category})
    return render(request, 'reports/product_sales.html', ctx)


@role_required(*MANAGERS)
def staff_performance(request):
    """Who sold what, who discounted and voided, and whose till came up short."""
    from django.db.models import Count

    ctx = report_context(request)
    start, end, branch = ctx['start'], ctx['end'], ctx['branch']
    rows = {r['served_by__username']: dict(r, voids=0, variance=Decimal('0.00'), shifts=0)
            for r in metrics.staff_performance(start, end, branch)}

    voided = filter_by_date(Sale.objects.filter(status=Sale.Status.VOIDED), start, end)
    shifts = filter_by_date(Shift.objects.filter(status=Shift.Status.CLOSED), start, end, field='opened_at')
    if branch:
        voided = voided.filter(branch=branch)
        shifts = shifts.filter(branch=branch)
    for r in voided.values('served_by__username').annotate(n=Count('id')):
        rows.setdefault(r['served_by__username'], {'served_by__username': r['served_by__username'],
                                                   'revenue': 0, 'count': 0, 'discounts': 0,
                                                   'variance': Decimal('0.00'), 'shifts': 0})['voids'] = r['n']
    for shift in shifts.select_related('cashier'):
        row = rows.setdefault(shift.cashier.username, {'served_by__username': shift.cashier.username,
                                                       'revenue': 0, 'count': 0, 'discounts': 0, 'voids': 0,
                                                       'variance': Decimal('0.00'), 'shifts': 0})
        row['variance'] += shift.variance or 0
        row['shifts'] += 1

    for r in rows.values():
        r['average'] = (r['revenue'] / r['count']).quantize(Decimal('0.01')) if r['count'] else None
    ctx['rows'] = sorted(rows.values(), key=lambda r: r['revenue'] or 0, reverse=True)
    return render(request, 'reports/staff_performance.html', ctx)
