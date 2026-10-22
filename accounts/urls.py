from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.staff_list, name='staff_list'),
    path('create/', views.staff_create, name='staff_create'),
    path('<int:user_id>/edit/', views.staff_edit, name='staff_edit'),
    path('<int:user_id>/password/', views.staff_set_password, name='staff_set_password'),
    path('audit-log/', views.audit_log, name='audit_log'),
    path('me/password/', views.change_password, name='change_password'),
]
