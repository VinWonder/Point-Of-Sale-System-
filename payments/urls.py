from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('mpesa/initiate/<int:sale_id>/', views.initiate_mpesa_payment, name='mpesa_initiate'),
    path('mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    path('mpesa/status/<int:payment_id>/', views.check_payment_status, name='mpesa_status'),
    path('mpesa/simulate/<int:payment_id>/', views.simulate_mpesa_result, name='mpesa_simulate'),
]
