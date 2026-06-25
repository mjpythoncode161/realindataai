from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class LeadOnlyStaffAccessMiddleware:
    """Restrict executive / telecaller users to dashboard and lead management URLs."""

    EXEMPT_PREFIXES = (
        "/login",
        "/logout",
        "/signup",
        "/static/",
        "/media/",
        "/admin/",
    )
    EXEMPT_EXACT = ("/",)
    ALLOWED_PREFIXES = (
        "/home/",
        "/account/profile/",
        "/leads/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if not user.is_authenticated or user.is_superuser:
            return self.get_response(request)
        if not user.is_lead_only_staff():
            return self.get_response(request)

        path = request.path
        if path in self.EXEMPT_EXACT:
            return self.get_response(request)
        if any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return self.get_response(request)
        if any(path.startswith(prefix) for prefix in self.ALLOWED_PREFIXES):
            return self.get_response(request)

        messages.warning(request, "You only have access to Lead Management.")
        return redirect("home")


class TrialAccessMiddleware:
    """Block expired trials and unapproved trial signups from the app."""

    EXEMPT_PREFIXES = (
        "/login",
        "/logout",
        "/signup",
        "/trial-expired",
        "/pending-approval",
        "/static/",
        "/media/",
        "/admin/",
    )
    EXEMPT_EXACT = ("/",)

    EXEMPT_NAMES = (
        "landing_home",
        "public_signup",
        "trial_expired",
        "pending_approval",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if not user.is_authenticated:
            return self.get_response(request)

        path = request.path
        if path in self.EXEMPT_EXACT:
            return self.get_response(request)
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return self.get_response(request)

        resolver = getattr(request, "resolver_match", None)
        url_name = resolver.url_name if resolver else None
        if url_name in self.EXEMPT_NAMES:
            return self.get_response(request)

        # Followup staff manage approvals; full app access for their role
        if user.has_any_role("followup"):
            return self.get_response(request)

        if getattr(user, "pending_signup_approval", False):
            if path != reverse("pending_approval"):
                return redirect("pending_approval")

        if getattr(user, "is_trial_account", False) and not user.trial_is_active:
            if path != reverse("trial_expired"):
                return redirect("trial_expired")

        return self.get_response(request)
