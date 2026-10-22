from functools import wraps
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden


def role_required(*roles):
    """Restrict a view to users whose .role is in `roles`."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                return HttpResponseForbidden(
                    "You don't have permission to access this page."
                )
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
