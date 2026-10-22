from django.urls import path
from . import views

app_name = 'registers'

urlpatterns = [
    path('shift/', views.my_shift, name='my_shift'),
    path('shifts/', views.shift_list, name='shift_list'),
    path('shifts/<int:shift_id>/', views.shift_detail, name='shift_detail'),
    path('shifts/<int:shift_id>/close/', views.shift_close, name='shift_close'),
    path('expenses/', views.expense_list, name='expense_list'),
]
