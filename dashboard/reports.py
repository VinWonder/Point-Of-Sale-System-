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
    {'url': 'reports:debt_aging', 'icon': 'bi-hourglass-split', 'title': 'Debt aging',
     'text': 'Who owes what and for how long: current, 31-60, 61-90 and 90+ days.'},
    {'url': 'reports:reorder', 'icon': 'bi-cart-check', 'title': 'Reorder list',
     'text': 'Items at or below reorder level with suggested order quantities from recent sales.'},
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


AGING_BUCKETS = [('current', 0, 30), ('d60', 31, 60), ('d90', 61, 90), ('over90', 91, None)]


@role_required(*MANAGERS)
def debt_aging(request):
    """Unpaid credit sales grouped by customer and by how old the debt is."""
    from django.utils import timezone
    from customers.models import Customer

    today = timezone.localdate()
    open_sales = (
        Sale.objects.filter(sale_type=Sale.SaleType.CREDIT, customer__isnull=False)
        .exclude(status=Sale.Status.VOIDED)
        .exclude(payment_status=Sale.PaymentStatus.PAID)
        .select_related('customer')
    )
    customers = {}
    for sale in open_sales:
        due = sale.balance_due
        if due <= 0:
            continue
        age = (today - timezone.localtime(sale.created_at).date()).days
        row = customers.setdefault(sale.customer_id, {
            'customer': sale.customer, 'oldest': age, 'total': Decimal('0.00'),
            **{key: Decimal('0.00') for key, _, _ in AGING_BUCKETS},
        })
        bucket = next(key for key, lo, hi in AGING_BUCKETS if hi is None or age <= hi)
        row[bucket] += due
        row['total'] += due
        row['oldest'] = max(row['oldest'], age)

    # Debt not linked to any sale (opening balances) is shown separately so totals reconcile.
    for customer in Customer.objects.filter(balance_owed__gt=0):
        row = customers.setdefault(customer.pk, {
            'customer': customer, 'oldest': None, 'total': Decimal('0.00'),
            **{key: Decimal('0.00') for key, _, _ in AGING_BUCKETS},
        })
        row['unallocated'] = max(customer.balance_owed - row['total'], Decimal('0.00'))
        row['total'] += row['unallocated']

    rows = sorted(customers.values(), key=lambda r: r['total'], reverse=True)
    totals = {key: sum((r[key] for r in rows), Decimal('0.00')) for key, _, _ in AGING_BUCKETS}
    totals['unallocated'] = sum((r.get('unallocated', Decimal('0.00')) for r in rows), Decimal('0.00'))
    totals['total'] = sum((r['total'] for r in rows), Decimal('0.00'))

    if request.GET.get('export') == 'csv':
        return csv_response('debt-aging', ['Customer', 'Phone', '0-30', '31-60', '61-90', '90+', 'Opening/other', 'Total'], (
            [r['customer'].name, r['customer'].phone_number, r['current'], r['d60'], r['d90'], r['over90'],
             r.get('unallocated', 0), r['total']] for r in rows
        ))
    return render(request, 'reports/debt_aging.html', {'rows': rows, 'totals': totals})


@role_required(*MANAGERS)
def reorder(request):
    """
    Low-stock items with a suggested order: enough to cover ~30 days of recent
    demand (and at least double the reorder level), minus what is on hand.
    """
    import math
    from datetime import timedelta
    from django.utils import timezone
    from inventory.models import Stock, SupplierPurchase
    from sales.models import SaleItem

    branch = scoped_branch(request)
    today = timezone.localdate()
    since = today - timedelta(days=30)
    stocks = Stock.objects.select_related('product', 'branch').filter(
        product__is_active=True, quantity__lte=F('product__reorder_level'),
    )
    if branch:
        stocks = stocks.filter(branch=branch)

    sold = SaleItem.objects.filter(sale__created_at__date__gte=since).exclude(sale__status=Sale.Status.VOIDED)
    demand = {
        (r['product_id'], r['sale__branch_id']): r['qty']
        for r in sold.values('product_id', 'sale__branch_id').annotate(qty=Sum(F('quantity') - F('returned_quantity')))
    }
    rows = []
    for st in stocks.order_by('branch__name', 'product__name'):
        monthly = demand.get((st.product_id, st.branch_id)) or 0
        target = max(monthly, st.product.reorder_level * 2)
        suggested = max(target - st.quantity, 0)
        last = SupplierPurchase.objects.filter(product=st.product).select_related('supplier').first()
        rows.append({
            'stock': st, 'monthly': monthly, 'daily': round(monthly / 30, 1),
            'days_left': math.floor(st.quantity / (monthly / 30)) if monthly and st.quantity > 0 else None,
            'suggested': suggested,
            'supplier': last.supplier if last else None,
            'unit_cost': last.cost_price if last else st.product.cost_price,
            'cost': suggested * (last.cost_price if last else st.product.cost_price),
        })

    if request.GET.get('export') == 'csv':
        return csv_response('reorder-list', ['Branch', 'SKU', 'Product', 'On hand', 'Reorder level', 'Sold last 30d',
                                             'Suggested order', 'Last supplier', 'Unit cost', 'Order cost'], (
            [r['stock'].branch.name, r['stock'].product.sku, r['stock'].product.name, r['stock'].quantity,
             r['stock'].product.reorder_level, r['monthly'], r['suggested'], r['supplier'] or '',
             r['unit_cost'], r['cost']] for r in rows
        ))
    return render(request, 'reports/reorder.html', {
        'rows': rows, 'branch': branch, 'branches': Branch.objects.filter(is_active=True).order_by('name'),
        'order_total': sum((r['cost'] for r in rows), Decimal('0.00')),
    })
