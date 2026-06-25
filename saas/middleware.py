from django.shortcuts import redirect
from django.urls import reverse


class SubscriptionAccessMiddleware:
    """
    Block users without an active paid subscription from the app.
    Replaces manual trial approval — pay first, then auto-start.
    """

    EXEMPT_PREFIXES = (
        "/login",
        "/logout",
        "/signup",
        "/pricing",
        "/saas/",
        "/subscription-expired",
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
        "saas_pricing",
        "saas_choose_plan",
        "saas_checkout",
        "saas_payment_verify",
        "saas_payment_success",
        "saas_payment_webhook",
        "subscription_expired",
        "trial_expired",
        "pending_approval",
        "platform_dashboard",
        "platform_organizations",
        "platform_organization_detail",
        "platform_plans",
        "platform_payments",
        "platform_users",
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

        if user.is_superuser:
            return self.get_response(request)

        if user.has_any_role("followup") and not getattr(user, "organization_id", None):
            return self.get_response(request)

        from saas.tenant import get_user_organization

        org = get_user_organization(user)

        if org is None:
            return self.get_response(request)

        if org.status == org.Status.PENDING_PAYMENT:
            if path != reverse("saas_choose_plan") and not path.startswith("/saas/checkout"):
                return redirect("saas_choose_plan")

        if org.status == org.Status.ACTIVE and org.is_subscription_active:
            return self.get_response(request)

        if path != reverse("subscription_expired"):
            return redirect("subscription_expired")

        return self.get_response(request)
