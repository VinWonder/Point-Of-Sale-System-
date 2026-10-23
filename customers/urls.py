from django.urls import path
from . import views

app_name = 'customers'

urlpatterns = [
    path('', views.customer_list, name='customer_list'),
    path('api/search/', views.customer_search_api, name='customer_search_api'),
    path('create/', views.customer_create, name='customer_create'),
    path('<int:customer_id>/', views.customer_detail, name='customer_detail'),
    path('<int:customer_id>/edit/', views.customer_edit, name='customer_edit'),
    path('<int:customer_id>/record-payment/', views.record_debt_payment_view, name='record_payment'),
]
