from django.urls import path
from . import views

app_name = 'branches'

urlpatterns = [
    path('', views.branch_list, name='branch_list'),
    path('create/', views.branch_create, name='branch_create'),
    path('<int:branch_id>/edit/', views.branch_edit, name='branch_edit'),
    path('transfers/', views.transfer_list, name='transfer_list'),
    path('transfers/create/', views.transfer_create, name='transfer_create'),
    path('transfers/<int:transfer_id>/receive/', views.transfer_receive, name='transfer_receive'),
]
