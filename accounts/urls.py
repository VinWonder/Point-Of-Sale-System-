from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.staff_list, name='staff_list'),
    path('create/', views.staff_create, name='staff_create'),
    path('<int:user_id>/edit/', views.staff_edit, name='staff_edit'),
]
