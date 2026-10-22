from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.shop_settings, name='settings'),
]
