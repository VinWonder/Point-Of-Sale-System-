from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('create/', views.product_create, name='product_create'),
    path('export/', views.product_export, name='product_export'),
    path('import/', views.product_import, name='product_import'),
    path('import/template/', views.product_import_template, name='product_import_template'),
    path('<int:product_id>/', views.product_detail, name='product_detail'),
    path('<int:product_id>/edit/', views.product_edit, name='product_edit'),
    path('stock/', views.stock_list, name='stock_list'),
    path('stock/adjust/', views.stock_adjust, name='stock_adjust'),
    path('restock/', views.supplier_purchase_create, name='supplier_purchase_create'),
    path('purchases/', views.purchase_list, name='purchase_list'),
    path('purchases/<int:purchase_id>/paid/', views.purchase_mark_paid, name='purchase_mark_paid'),
    path('categories/', views.category_list, name='category_list'),
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_form, name='supplier_create'),
    path('suppliers/<int:supplier_id>/edit/', views.supplier_form, name='supplier_edit'),
]
