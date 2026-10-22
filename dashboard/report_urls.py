from django.urls import path

from . import reports

app_name = 'reports'

urlpatterns = [
    path('', reports.report_index, name='index'),
    path('profit-and-loss/', reports.profit_and_loss, name='profit_and_loss'),
]
