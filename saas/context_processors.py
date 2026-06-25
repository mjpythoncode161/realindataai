from saas.tenant import get_request_organization, organization_has_full_access


def saas_context(request):
    org = get_request_organization(request) if request.user.is_authenticated else None
    plan = org.plan if org else None
    full_access = organization_has_full_access(org) if org else False
    if request.user.is_authenticated and request.user.is_superuser:
        full_access = True
    return {
        "current_organization": org,
        "current_plan": plan,
        "org_has_full_access": full_access,
        "saas_demo_mode": __import__("django.conf", fromlist=["settings"]).settings.SAAS_DEMO_MODE,
    }
