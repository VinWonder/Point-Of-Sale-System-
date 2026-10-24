from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import F, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from accounts.models import User
from branches.models import Branch
from customers.models import Customer, DebtPayment
from inventory.models import Stock
from payments.models import Payment
from registers.models import Expense, Shift
from sales.models import Quotation, QuotationItem, Sale
from . import metrics


def scoped_branch(request):
    """Owners may pick any branch (or all); everyone else sees their own branch."""
    if request.user.role == User.Role.OWNER:
        branch_id = request.GET.get('branch', '')
        return Branch.objects.filter(pk=branch_id).first() if branch_id.isdigit() else None
    return request.user.branch


def growth(now, before):
    if not before:
        return None
    return round(float((now - before) / before * 100), 1)


def _scope(qs, branch, field='branch'):
    return qs.filter(**{field: branch}) if branch else qs


@login_required
def index(request):
    today = timezone.localdate()
    branch = scoped_branch(request)
    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    # Same number of days into last month, so the comparison is fair mid-month
    last_month_same_day = min(last_month_start + (today - month_start), last_month_end)

    today_totals = metrics.sales_totals(today, today, branch)
    yesterday_totals = metrics.sales_totals(today - timedelta(days=1), today - timedelta(days=1), branch)
    month_totals = metrics.sales_totals(month_start, today, branch)
    last_month_totals = metrics.sales_totals(last_month_start, last_month_same_day, branch)
    series = metrics.daily_series(today - timedelta(days=29), today, branch)

    # --- money in today, by how it was paid ---
    payments_today = _scope(Payment.objects.filter(
        status=Payment.Status.SUCCESS, created_at__date=today, debt_payment__isnull=True,
    ).exclude(method=Payment.Method.CREDIT_NOTE), branch, 'sale__branch')
    by_method = {r['method']: r['t'] for r in payments_today.values('method').annotate(t=Sum('amount'))}
    debt_today = _scope(DebtPayment.objects.filter(created_at__date=today), branch)
    for r in debt_today.values('method').annotate(t=Sum('amount')):
        by_method[r['method']] = by_method.get(r['method'], Decimal('0')) + r['t']
    collected_today = sum(by_method.values(), Decimal('0.00'))
    collections = [
        {'label': label, 'icon': icon, 'amount': by_method.get(key, Decimal('0.00'))}
        for key, label, icon in [('CASH', 'Cash', 'bi-cash-stack'), ('MPESA', 'M-Pesa', 'bi-phone'),
                                 ('CARD', 'Card', 'bi-credit-card'), ('BANK', 'Bank / cheque', 'bi-bank')]
    ]
    collections[3]['amount'] += by_method.get('CHEQUE', Decimal('0.00'))

    # --- things that need someone to act ---
    unpaid = ~Q(status=Sale.Status.VOIDED) & Q(payment_status__in=[Sale.PaymentStatus.UNPAID, Sale.PaymentStatus.PARTIAL])
    invoices = _scope(Sale.objects.filter(invoice_number__isnull=False), branch)
    overdue = invoices.filter(unpaid, due_date__lt=today)
    overdue_sum = overdue.aggregate(t=Sum('total'), p=Sum('amount_paid'))
    quotes = _scope(Quotation.objects.all(), branch)
    open_quotes = quotes.filter(status=Quotation.Status.DRAFT).exclude(valid_until__lt=today)
    expiring = open_quotes.filter(valid_until__lte=today + timedelta(days=3))
    open_value = QuotationItem.objects.filter(quotation__in=open_quotes).aggregate(
        v=Sum(F('quantity') * F('unit_price')))['v'] or Decimal('0.00')
    month_quotes = quotes.filter(created_at__date__gte=month_start)
    month_quote_count = month_quotes.count()
    converted = month_quotes.filter(status=Quotation.Status.CONVERTED).count()
    low_stock = _scope(Stock.objects.select_related('product', 'branch').filter(
        product__is_active=True, quantity__lte=F('product__reorder_level'),
    ), branch)
    blocked = Customer.objects.filter(balance_owed__gt=F('credit_limit'))
    shifts = _scope(Shift.objects.filter(status=Shift.Status.OPEN).select_related('cashier', 'branch'), branch)

    attention = [
        {'show': overdue.exists(), 'icon': 'bi-alarm', 'tone': 'danger',
         'title': f'{overdue.count()} overdue invoice{"s" if overdue.count() != 1 else ""}',
         'detail': f'KES {(overdue_sum["t"] or 0) - (overdue_sum["p"] or 0):,.0f} past due date',
         'url': 'sales:invoice_list', 'query': '?status=overdue', 'action': 'Chase'},
        {'show': expiring.exists(), 'icon': 'bi-hourglass-split', 'tone': 'warning',
         'title': f'{expiring.count()} quotation{"s" if expiring.count() != 1 else ""} expiring soon',
         'detail': 'Call the customer before the prices lapse', 'url': 'sales:quotation_list',
         'query': '?status=open', 'action': 'Follow up'},
        {'show': low_stock.exists(), 'icon': 'bi-box-seam', 'tone': 'warning',
         'title': f'{low_stock.count()} item{"s" if low_stock.count() != 1 else ""} low on stock',
         'detail': ', '.join(s.product.name for s in low_stock.order_by('quantity')[:3]),
         'url': 'reports:reorder' if request.user.role != User.Role.CASHIER else 'inventory:stock_list',
         'query': '' if request.user.role != User.Role.CASHIER else '?level=low', 'action': 'Reorder'},
        {'show': blocked.exists(), 'icon': 'bi-person-x', 'tone': 'danger',
         'title': f'{blocked.count()} customer{"s" if blocked.count() != 1 else ""} over credit limit',
         'detail': 'Blocked from buying until they pay', 'url': 'customers:customer_list',
         'query': '?status=blocked', 'action': 'View'},
        {'show': shifts.exists(), 'icon': 'bi-cash-coin', 'tone': 'info',
         'title': f'{shifts.count()} till{"s" if shifts.count() != 1 else ""} open',
         'detail': ', '.join(s.cashier.username for s in shifts[:4]), 'url': 'registers:shift_list',
         'query': '', 'action': 'Check'},
    ]
    attention = [a for a in attention if a['show']]

    month_expenses = _scope(Expense.objects.filter(created_at__date__gte=month_start), branch).aggregate(
        s=Sum('amount'))['s'] or Decimal('0.00')
    top = metrics.top_products(today - timedelta(days=29), today, branch, limit=6)
    week = [d['revenue'] for d in series[-7:]]

    context = {
        'branch': branch,
        'branches': Branch.objects.filter(is_active=True).order_by('name'),
        'today': today_totals,
        'today_growth': growth(today_totals['revenue'], yesterday_totals['revenue']),
        'month': month_totals,
        'month_growth': growth(month_totals['revenue'], last_month_totals['revenue']),
        'month_expenses': month_expenses,
        'month_net_profit': month_totals['gross_profit'] - month_expenses,
        'collected_today': collected_today,
        'collections': collections,
        'attention': attention,
        'open_quotes': open_quotes.count(),
        'open_quotes_value': open_value,
        'quote_conversion': round(converted / month_quote_count * 100) if month_quote_count else None,
        'unpaid_invoices': invoices.filter(unpaid).count(),
        'unpaid_invoice_balance': (lambda a: (a['t'] or 0) - (a['p'] or 0))(
            invoices.filter(unpaid).aggregate(t=Sum('total'), p=Sum('amount_paid'))),
        'debt_total': Customer.objects.aggregate(s=Sum('balance_owed'))['s'] or Decimal('0.00'),
        'low_stock_count': low_stock.count(),
        'spark_week': week,
        'recent_quotes': quotes.select_related('customer').order_by('-created_at')[:6],
        'recent_invoices': invoices.select_related('customer').order_by('-invoice_number')[:6],
        'recent_sales': _scope(Sale.objects.select_related('customer', 'served_by'), branch).order_by('-created_at')[:6],
        'top_debtors': Customer.objects.filter(balance_owed__gt=0).order_by('-balance_owed')[:5],
        'chart': {
            'labels': [d['day'].strftime('%d %b') for d in series],
            'revenue': [d['revenue'] for d in series],
            'counts': [d['count'] for d in series],
            'mix': metrics.payment_mix(month_start, today, branch),
            'top_labels': [p['product__name'] for p in top],
            'top_revenue': [float(p['revenue']) for p in top],
            'branches': [
                {'name': b['branch__name'], 'revenue': float(b['revenue'])}
                for b in metrics.branch_comparison(month_start, today)
            ] if request.user.role == User.Role.OWNER and not branch else [],
        },
    }
    return render(request, 'dashboard/index.html', context)
