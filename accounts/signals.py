from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from .models import AuditLog


@receiver(user_logged_in)
def record_login(sender, request, user, **kwargs):
    AuditLog.objects.create(user=user, action='Logged in', entity='User', entity_id=str(user.pk))


@receiver(user_login_failed)
def record_failed_login(sender, credentials, request=None, **kwargs):
    AuditLog.objects.create(
        user=None, action='Failed login attempt', entity='User',
        details=f"username={credentials.get('username', '')}",
    )
