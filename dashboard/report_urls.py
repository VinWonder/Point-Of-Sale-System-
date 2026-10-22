from django.urls import path

from . import reports

app_name = 'reports'

urlpatterns = [
    path('', reports.report_index, name='index'),
    path('profit-and-loss/', reports.profit_and_loss, name='profit_and_loss'),
    path('products/', reports.product_sales, name='product_sales'),
    path('staff/', reports.staff_performance, name='staff_performance'),
    path('debt-aging/', reports.debt_aging, name='debt_aging'),
]
