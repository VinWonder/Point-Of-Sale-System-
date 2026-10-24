import calendar
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import F, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from accounts.models import User
from branches.models import Branch
from core.models import ShopSettings
from customers.models import Customer
from inventory.models import Stock
from registers.models import Expense, Shift
from sales.models import Quotation, QuotationItem, Sale
from . import metrics

# Fixed colour per payment method (validated reference palette slots 1-4, in slot order).
PAYMENT_SEGMENTS = [
    ('CASH', 'Cash', '#2a78d6', 'bi-cash-stack'),
    ('CARD', 'Card', '#eb6834', 'bi-credit-card'),
    ('MPESA', 'M-Pesa', '#1baf7a', 'bi-phone'),
    ('BANK', 'Bank / cheque', '#eda100', 'bi-bank'),
]


def scoped_branch(request):
    """Owners may pick any branch (or all); everyone else sees their own branch."""
    if request.user.role == User.Role.OWNER:
        branch_id = request.GET.get('branch', '')
        return Branch.objects.filter(pk=branch_id).first() if branch_id.isdigit() else None
    return request.user.branch


def growth(now, before):
    if not before:
        return None
    return round(float((Decimal(now) - Decimal(before)) / Decimal(before) * 100), 1)


def _scope(qs, branch, field='branch'):
    return qs.filter(**{field: branch}) if branch else qs


def _kpi(key, label, icon, value, previous, spark, money=True, tone='blue'):
    return {
        'key': key, 'label': label, 'icon': icon, 'value': value, 'previous': previous,
        'delta': growth(value, previous), 'spark': spark, 'money': money, 'tone': tone,
    }


def _monthly_target(today, branch, settings):
    """Progress towards the monthly goal and where the month will land at today's pace."""
    target = settings.monthly_sales_target
    if not target or branch is not None:
        return None
    month_start = today.replace(day=1)
    sold = metrics.sales_totals(month_start, today)['revenue']
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    projected = sold / today.day * days_in_month
    percent = float(sold / target * 100)
    return {
        'target': target, 'sold': sold, 'percent': round(percent, 1), 'ring': min(percent, 100),
        'projected': projected.quantize(Decimal('1')), 'on_track': projected >= target,
        'remaining': max(target - sold, Decimal('0')), 'days_left': days_in_month - today.day,
        'per_day_needed': (max(target - sold, Decimal('0')) / max(days_in_month - today.day, 1)).quantize(Decimal('1')),
    }


def _attention(request, branch, today):
    unpaid = ~Q(status=Sale.Status.VOIDED) & Q(payment_status__in=[Sale.PaymentStatus.UNPAID, Sale.PaymentStatus.PARTIAL])
    invoices = _scope(Sale.objects.filter(invoice_number__isnull=False), branch)
    overdue = invoices.filter(unpaid, due_date__lt=today)
    overdue_sum = overdue.aggregate(t=Sum('total'), p=Sum('amount_paid'))
    open_quotes = _scope(Quotation.objects.filter(status=Quotation.Status.DRAFT), branch).exclude(valid_until__lt=today)
    expiring = open_quotes.filter(valid_until__lte=today + timedelta(days=3))
    low_stock = _scope(Stock.objects.select_related('product').filter(
        product__is_active=True, quantity__lte=F('product__reorder_level')), branch)
    blocked = Customer.objects.filter(balance_owed__gt=F('credit_limit'))
    shifts = _scope(Shift.objects.filter(status=Shift.Status.OPEN).select_related('cashier'), branch)
    cashier = request.user.role == User.Role.CASHIER

    def plural(n, word):
        return f'{n} {word}{"" if n == 1 else "s"}'

    items = [
        (overdue.count(), 'bi-alarm', 'danger', lambda n: plural(n, 'overdue invoice'),
         f'KES {(overdue_sum["t"] or 0) - (overdue_sum["p"] or 0):,.0f} past due date',
         'sales:invoice_list', '?status=overdue', 'Chase'),
        (expiring.count(), 'bi-hourglass-split', 'warning', lambda n: plural(n, 'quotation') + ' expiring soon',
         'Call the customer before the prices lapse', 'sales:quotation_list', '?status=open', 'Follow up'),
        (low_stock.count(), 'bi-box-seam', 'warning', lambda n: plural(n, 'item') + ' low on stock',
         ', '.join(s.product.name for s in low_stock.order_by('quantity')[:3]),
         'inventory:stock_list' if cashier else 'reports:reorder', '?level=low' if cashier else '', 'Reorder'),
        (blocked.count(), 'bi-person-x', 'danger', lambda n: plural(n, 'customer') + ' over credit limit',
         'Blocked from buying until they pay', 'customers:customer_list', '?status=blocked', 'View'),
        (shifts.count(), 'bi-cash-coin', 'info', lambda n: plural(n, 'till') + ' open',
         ', '.join(s.cashier.username for s in shifts[:4]), 'registers:shift_list', '', 'Check'),
    ]
    return [
        {'icon': icon, 'tone': tone, 'title': title(n), 'detail': detail, 'url': url, 'query': query, 'action': action}
        for n, icon, tone, title, detail, url, query, action in items if n
    ]


@login_required
def index(request):
    today = timezone.localdate()
    branch = scoped_branch(request)
    settings = ShopSettings.load()
    period = request.GET.get('period', 'today')
    if period not in metrics.PERIODS:
        period = 'today'
    start, end, prev_start, prev_end = metrics.period_range(period, today)
    see_profit = request.user.role != User.Role.CASHIER

    current = metrics.sales_totals(start, end, branch)
    previous = metrics.sales_totals(prev_start, prev_end, branch)
    paid_now = metrics.collected(start, end, branch)
    paid_before = metrics.collected(prev_start, prev_end, branch)
    collected_now = sum(paid_now.values(), Decimal('0.00'))
    collected_before = sum(paid_before.values(), Decimal('0.00'))

    # --- main chart: this period vs the one before ---
    if period == 'today':
        now_series = metrics.hourly_series(today, branch)
        before_series = metrics.hourly_series(today - timedelta(days=1), branch)
        labels = [f"{p['hour']:02d}:00" for p in now_series]
        compare_label = 'Yesterday'
        spark_source = [p['revenue'] for p in now_series]
    else:
        now_series = metrics.daily_series(start, end, branch)
        before_series = metrics.daily_series(prev_start, prev_end, branch)
        labels = [d['day'].strftime('%d %b') for d in now_series]
        compare_label = 'Previous period'
        spark_source = [d['revenue'] for d in now_series]
    spark_counts = [p['count'] for p in now_series]

    kpis = [
        _kpi('revenue', 'Revenue', 'bi-graph-up-arrow', current['revenue'], previous['revenue'], spark_source),
        _kpi('collected', 'Money collected', 'bi-wallet2', collected_now, collected_before, None, tone='green'),
        _kpi('count', 'Transactions', 'bi-receipt', current['count'], previous['count'], spark_counts,
             money=False, tone='violet'),
    ]
    if see_profit:
        kpis.append(_kpi('profit', 'Gross profit', 'bi-piggy-bank', current['gross_profit'],
                         previous['gross_profit'], None, tone='orange'))
    else:
        kpis.append(_kpi('average', 'Average sale', 'bi-basket', current['average_sale'],
                         previous['average_sale'], None, tone='orange'))

    # --- payment mix (fixed colour per method) ---
    paid_now['BANK'] = paid_now.get('BANK', Decimal('0')) + paid_now.pop('CHEQUE', Decimal('0'))
    mix = [
        {'label': label, 'color': color, 'icon': icon, 'amount': paid_now.get(key, Decimal('0.00')),
         'share': round(float(paid_now.get(key, 0) / collected_now * 100), 1) if collected_now else 0}
        for key, label, color, icon in PAYMENT_SEGMENTS
    ]

    # --- quotes and invoices pipeline ---
    quotes = _scope(Quotation.objects.all(), branch)
    open_quotes = quotes.filter(status=Quotation.Status.DRAFT).exclude(valid_until__lt=today)
    period_quotes = metrics._between(quotes, start, end)
    period_quote_count = period_quotes.count()
    converted = period_quotes.filter(status=Quotation.Status.CONVERTED).count()
    unpaid = ~Q(status=Sale.Status.VOIDED) & Q(payment_status__in=[Sale.PaymentStatus.UNPAID, Sale.PaymentStatus.PARTIAL])
    invoices = _scope(Sale.objects.filter(invoice_number__isnull=False), branch)
    unpaid_agg = invoices.filter(unpaid).aggregate(t=Sum('total'), p=Sum('amount_paid'))

    expenses = _scope(metrics._between(Expense.objects.all(), start, end), branch).aggregate(s=Sum('amount'))['s'] or 0
    staff = metrics.staff_performance(start, end, branch)[:5]
    top_staff = float(staff[0]['revenue']) if staff else 0
    branches_board = metrics.branch_comparison(start, end) if request.user.role == User.Role.OWNER and not branch else []
    top_branch = float(branches_board[0]['revenue']) if branches_board else 0

    context = {
        'period': period, 'periods': metrics.PERIODS, 'period_label': metrics.PERIODS[period],
        'compare_text': {'today': 'vs yesterday', '7d': 'vs previous 7 days', '30d': 'vs previous 30 days',
                         'month': 'vs same days last month'}[period],
        'start': start, 'end': end, 'branch': branch,
        'branches': Branch.objects.filter(is_active=True).order_by('name'),
        'see_profit': see_profit,
        'kpis': kpis,
        'current': current,
        'expenses': expenses,
        'net_profit': current['gross_profit'] - Decimal(expenses),
        'collected_now': collected_now,
        'mix': mix,
        'target': _monthly_target(today, branch, settings),
        'attention': _attention(request, branch, today),
        'open_quotes': open_quotes.count(),
        'open_quotes_value': QuotationItem.objects.filter(quotation__in=open_quotes).aggregate(
            v=Sum(F('quantity') * F('unit_price')))['v'] or Decimal('0.00'),
        'quote_conversion': round(converted / period_quote_count * 100) if period_quote_count else None,
        'unpaid_invoices': invoices.filter(unpaid).count(),
        'unpaid_invoice_balance': (unpaid_agg['t'] or 0) - (unpaid_agg['p'] or 0),
        'debt_total': Customer.objects.aggregate(s=Sum('balance_owed'))['s'] or Decimal('0.00'),
        'stock': metrics.stock_health(branch),
        'staff_board': [dict(s, share=float(s['revenue']) / top_staff * 100 if top_staff else 0) for s in staff],
        'branch_board': [dict(b, share=float(b['revenue']) / top_branch * 100 if top_branch else 0) for b in branches_board],
        'recent_quotes': quotes.select_related('customer').order_by('-created_at')[:6],
        'recent_invoices': invoices.select_related('customer').order_by('-invoice_number')[:6],
        'recent_sales': _scope(Sale.objects.select_related('customer', 'served_by'), branch).order_by('-created_at')[:6],
        'top_debtors': Customer.objects.filter(balance_owed__gt=0).order_by('-balance_owed')[:5],
        'updated_at': timezone.localtime(),
        'chart': {
            'labels': labels,
            'current': [p['revenue'] for p in now_series],
            'previous': [p['revenue'] for p in before_series][:len(now_series)],
            'counts': spark_counts,
            'compareLabel': compare_label,
            'hours': metrics.busiest_hours(start, end, branch),
            'categories': metrics.category_sales(start, end, branch),
        },
    }
    return render(request, 'dashboard/index.html', context)
