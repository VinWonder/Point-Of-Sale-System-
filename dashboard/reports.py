from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import User
from branches.models import Branch
from core.filters import PRESETS, date_range_from_request, filter_by_date
from registers.models import Expense
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
