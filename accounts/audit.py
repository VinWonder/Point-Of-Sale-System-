from .models import AuditLog


def log_action(user, action, obj=None, details=''):
    """
    Record who did what. `obj` is any model instance; its class name and pk
    become the entity/entity_id so the log can link back to it.
    """
    entity = obj.__class__.__name__ if obj is not None else ''
    entity_id = str(obj.pk) if obj is not None and obj.pk is not None else ''
    return AuditLog.objects.create(
        user=user if getattr(user, 'is_authenticated', False) else None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=details,
    )
