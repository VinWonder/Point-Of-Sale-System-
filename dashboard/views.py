import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F
from django.shortcuts import render
from django.utils import timezone

from sales.models import Sale, SaleItem
from inventory.models import Stock
from customers.models import Customer


@login_required
def index(request):
    today = timezone.now().date()

    sales_today = Sale.objects.filter(created_at__date=today)
    total_today = sum((s.total for s in sales_today), 0)

    low_stock = Stock.objects.select_related('product', 'branch').filter(
        quantity__lte=F('product__reorder_level')
    )[:10]

    defaulters = [c for c in Customer.objects.all() if c.is_defaulter][:10]

    # --- Last 7 days sales trend (for Chart.js line chart) ---
    day_labels, day_totals = [], []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_sales = Sale.objects.filter(created_at__date=day)
        day_totals.append(float(sum((s.total for s in day_sales), 0)))
        day_labels.append(day.strftime('%a'))

    # --- Top 5 products by quantity sold (for Chart.js bar chart) ---
    top_products = (
        SaleItem.objects.values('product__name')
        .annotate(total_qty=Sum('quantity'))
        .order_by('-total_qty')[:5]
    )
    product_labels = [p['product__name'] for p in top_products]
    product_qtys = [p['total_qty'] for p in top_products]

    context = {
        'sales_today_count': sales_today.count(),
        'total_today': total_today,
        'low_stock': low_stock,
        'defaulters': defaulters,
        'day_labels': json.dumps(day_labels),
        'day_totals': json.dumps(day_totals),
        'product_labels': json.dumps(product_labels),
        'product_qtys': json.dumps(product_qtys),
    }
    return render(request, 'dashboard/index.html', context)
