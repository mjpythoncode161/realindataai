from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect


def platform_superuser_required(view_func):
    """Only Django superusers (platform owners) may access."""

    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            return HttpResponseForbidden("Platform super admin access required.")
        return view_func(request, *args, **kwargs)

    return wrapper
