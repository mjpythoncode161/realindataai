"""Tenant resolution, queryset scoping, and org assignment helpers."""

from django.db.models import Q

from saas.models import Organization, OrganizationMembership


def get_user_organization(user):
    """Return the primary organization for a user, or None for platform staff."""
    if not user or not user.is_authenticated:
        return None
    org = getattr(user, "organization", None)
    if org:
        return org
    membership = (
        OrganizationMembership.objects.filter(user=user)
        .select_related("organization", "organization__plan")
        .order_by("-is_owner", "-joined_at")
        .first()
    )
    return membership.organization if membership else None


def organization_has_full_access(org):
    if not org:
        return False
    return org.is_subscription_active


def get_request_organization(request):
    org = getattr(request, "organization", None)
    if org is not None:
        return org
    if request.user.is_authenticated:
        org = get_user_organization(request.user)
        request.organization = org
        return org
    return None


def _is_platform_superuser(request):
    return request.user.is_authenticated and request.user.is_superuser and not get_request_organization(request)


def scope_queryset_to_org(queryset, request, org_field="organization"):
    """Filter queryset to current tenant."""
    if _is_platform_superuser(request):
        return queryset
    org = get_request_organization(request)
    if org is None:
        return queryset.none()
    return queryset.filter(**{org_field: org})


def tenant_users(request):
    from accounts.models import Users

    qs = Users.objects.all()
    if _is_platform_superuser(request):
        return qs
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(organization=org)


def tenant_staff_users(request):
    from accounts.models import Users, users_with_any_role_query

    staff_roles = ("admin", "manager", "executive", "telecaller", "accounts", "followup")
    return tenant_users(request).filter(users_with_any_role_query(*staff_roles)).distinct()


def tenant_customers(request):
    from accounts.models import Customer

    qs = Customer.objects.select_related("u_id")
    if _is_platform_superuser(request):
        return qs.all()
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(u_id__organization=org)


def tenant_projects(request):
    from bookings.models import Project

    return scope_queryset_to_org(Project.objects.all(), request)


def tenant_bookings(request):
    from bookings.models import BookingMaster

    qs = BookingMaster.objects.all()
    if _is_platform_superuser(request):
        return qs
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(Q(organization=org) | Q(p_id__organization=org)).distinct()


def tenant_receipts(request):
    from bookings.models import ReceiptMaster

    qs = ReceiptMaster.objects.all()
    if _is_platform_superuser(request):
        return qs
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(Q(b_id__organization=org) | Q(b_id__p_id__organization=org)).distinct()


def tenant_payments(request):
    from bookings.models import Payment

    qs = Payment.objects.all()
    if _is_platform_superuser(request):
        return qs
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(Q(b_id__organization=org) | Q(b_id__p_id__organization=org)).distinct()


def tenant_cancelled_plots(request):
    from bookings.models import CancelledPlot

    qs = CancelledPlot.objects.all()
    if _is_platform_superuser(request):
        return qs
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(Q(b_id__organization=org) | Q(b_id__p_id__organization=org)).distinct()


def tenant_leads(request):
    from accounts.models import Lead

    qs = Lead.objects.all()
    if _is_platform_superuser(request):
        return qs
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(Q(organization=org) | Q(p_id__organization=org)).distinct()


def tenant_activity_logs(request):
    from accounts.models import ActivityLog

    qs = ActivityLog.objects.all()
    if _is_platform_superuser(request):
        return qs
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(
        Q(organization=org)
        | Q(organization__isnull=True, user__organization=org)
    ).distinct()


def tenant_ledgers(request):
    from tally.models import LedgerMaster

    qs = LedgerMaster.objects.all()
    if _is_platform_superuser(request):
        return qs
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(organization=org)


def tenant_vouchers(request):
    from tally.models import Voucher

    qs = Voucher.objects.all()
    if _is_platform_superuser(request):
        return qs
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(organization=org)


def tenant_agents(request):
    from bookings.models import AgentMaster

    qs = AgentMaster.objects.all()
    if _is_platform_superuser(request):
        return qs
    org = get_request_organization(request)
    if not org:
        return qs.none()
    return qs.filter(u_id__organization=org)


def assign_user_to_organization(user, org, is_owner=False):
    """Link user to tenant; creates membership."""
    if not org or not user:
        return
    user.organization = org
    user.save(update_fields=["organization"])
    OrganizationMembership.objects.get_or_create(
        organization=org,
        user=user,
        defaults={"is_owner": is_owner},
    )


def user_can_access_feature(user, feature_name):
    if user.is_superuser:
        return True
    org = get_user_organization(user)
    if not org:
        return True
    return org.has_feature(feature_name)


def organization_within_limits(org, resource):
    if not org:
        return True
    if organization_has_full_access(org):
        return True
    if not org.plan:
        return True
    plan = org.plan
    if resource == "projects" and plan.max_projects:
        from bookings.models import Project

        count = Project.objects.filter(organization=org).count()
        return count < plan.max_projects
    if resource == "users" and plan.max_users:
        count = OrganizationMembership.objects.filter(organization=org).count()
        return count < plan.max_users
    return True


def get_booking_agent_settings_for_org(org):
    from bookings.models import BookingAgentSettings

    if not org:
        return get_booking_agent_settings_legacy()
    settings_obj, _ = BookingAgentSettings.objects.get_or_create(
        organization=org,
        defaults={
            "company_name": org.name,
        },
    )
    return settings_obj


def get_booking_agent_settings_legacy():
    from bookings.models import BookingAgentSettings

    legacy = BookingAgentSettings.objects.filter(organization__isnull=True).first()
    if legacy:
        return legacy
    return BookingAgentSettings.objects.create(
        company_name="LANDLINK REAL ESTATE",
    )


def get_booking_agent_settings_for_request(request):
    org = get_request_organization(request)
    if org:
        return get_booking_agent_settings_for_org(org)
    return get_booking_agent_settings_legacy()
