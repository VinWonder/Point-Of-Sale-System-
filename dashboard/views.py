from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum
from django.shortcuts import render
from django.utils import timezone

from accounts.models import User
from branches.models import Branch
from customers.models import Customer
from inventory.models import Stock
from registers.models import Expense, Shift
from sales.models import Quotation, QuotationItem, Sale
from . import metrics


def scoped_branch(request):
    """Owners may pick any branch (or all); everyone else sees their own branch."""
    if request.user.role == User.Role.OWNER:
        branch_id = request.GET.get('branch', '')
        return Branch.objects.filter(pk=branch_id).first() if branch_id.isdigit() else None
    return request.user.branch


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

    def growth(now, before):
        if not before:
            return None
        return round(float((now - before) / before * 100), 1)

    stocks = Stock.objects.select_related('product', 'branch').filter(
        product__is_active=True, quantity__lte=F('product__reorder_level'),
    )
    expenses = Expense.objects.filter(created_at__date__gte=month_start)
    shifts = Shift.objects.filter(status=Shift.Status.OPEN).select_related('cashier', 'branch')
    recent = Sale.objects.select_related('customer', 'branch', 'served_by')
    if branch:
        stocks = stocks.filter(branch=branch)
        expenses = expenses.filter(branch=branch)
        shifts = shifts.filter(branch=branch)
        recent = recent.filter(branch=branch)

    month_expenses = expenses.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

    quotes = Quotation.objects.all()
    if branch:
        quotes = quotes.filter(branch=branch)
    open_quotes = quotes.filter(status=Quotation.Status.DRAFT).exclude(valid_until__lt=today)
    open_value = QuotationItem.objects.filter(quotation__in=open_quotes).aggregate(
        v=Sum(F('quantity') * F('unit_price')))['v'] or Decimal('0.00')
    month_quotes = quotes.filter(created_at__date__gte=month_start)
    month_quote_count = month_quotes.count()
    converted = month_quotes.filter(status=Quotation.Status.CONVERTED).count()
    series = metrics.daily_series(today - timedelta(days=13), today, branch)
    top = metrics.top_products(today - timedelta(days=29), today, branch, limit=7)

    context = {
        'branch': branch,
        'branches': Branch.objects.filter(is_active=True).order_by('name'),
        'today': today_totals,
        'today_growth': growth(today_totals['revenue'], yesterday_totals['revenue']),
        'month': month_totals,
        'month_growth': growth(month_totals['revenue'], last_month_totals['revenue']),
        'month_expenses': month_expenses,
        'month_net_profit': month_totals['gross_profit'] - month_expenses,
        'open_quotes': open_quotes.count(),
        'open_quotes_value': open_value,
        'quote_conversion': round(converted / month_quote_count * 100) if month_quote_count else None,
        'debt_total': Customer.objects.aggregate(s=Sum('balance_owed'))['s'] or Decimal('0.00'),
        'low_stock': stocks.order_by('quantity')[:8],
        'low_stock_count': stocks.count(),
        'top_debtors': Customer.objects.filter(balance_owed__gt=0).order_by('-balance_owed')[:6],
        'recent_sales': recent[:8],
        'open_shifts': shifts,
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
