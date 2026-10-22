from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'
    verbose_name = 'Shop Settings'


class DarajaConfig(AppConfig):
    """
    django-daraja ships migrations with AutoField ids but doesn't declare
    default_auto_field, so our BigAutoField default made Django report a
    phantom pending migration for it. Pin it to what its migrations use.
    """
    name = 'django_daraja'
    default_auto_field = 'django.db.models.AutoField'
