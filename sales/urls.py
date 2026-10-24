from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    path('pos/', views.pos_screen, name='pos'),
    path('create/', views.create_sale, name='create_sale'),
    path('quotation/new/', views.quotation_desk, name='quotation_desk'),
    path('invoice/new/', views.invoice_desk, name='invoice_desk'),
    path('invoice/create/', views.create_invoice_view, name='create_invoice'),
    path('quotation/<int:quotation_id>/edit/', views.quotation_desk, name='quotation_edit'),
    path('quotation/<int:quotation_id>/requote/', views.quotation_requote, name='quotation_requote'),
    path('quotation/create/', views.create_quotation, name='create_quotation'),
    path('quotation/<int:quotation_id>/convert/', views.convert_quotation, name='convert_quotation'),
    path('quotation/<int:quotation_id>/', views.quotation_view, name='quotation'),
    path('quotations/', views.quotation_list, name='quotation_list'),
    path('receipt/<int:sale_id>/', views.receipt, name='receipt'),
    path('invoice/<int:sale_id>/', views.sale_invoice, name='invoice'),
    path('invoice/<int:sale_id>/issue/', views.issue_invoice_view, name='issue_invoice'),
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('<int:sale_id>/return/', views.sale_return_create, name='sale_return'),
    path('<int:sale_id>/void/', views.void_sale_view, name='void_sale'),
    path('history/', views.sale_list, name='sale_list'),
    path('history/export/', views.sale_export, name='sale_export'),
]
