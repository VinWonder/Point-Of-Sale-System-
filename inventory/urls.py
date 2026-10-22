from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('create/', views.product_create, name='product_create'),
    path('<int:product_id>/', views.product_detail, name='product_detail'),
    path('<int:product_id>/edit/', views.product_edit, name='product_edit'),
    path('stock/', views.stock_list, name='stock_list'),
    path('stock/adjust/', views.stock_adjust, name='stock_adjust'),
    path('restock/', views.supplier_purchase_create, name='supplier_purchase_create'),
]
