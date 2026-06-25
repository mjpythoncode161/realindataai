from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Users
from saas.decorators import platform_superuser_required
from saas.forms import ExtendRenewalForm, OrganizationStatusForm, SubscriptionPlanForm
from saas.models import Organization, OrganizationMembership, PaymentOrder, SubscriptionPlan


def _org_stats():
    now = timezone.now()
    renew_soon = now + timedelta(days=7)
    qs = Organization.objects.all()
    return {
        "total": qs.count(),
        "active": qs.filter(status=Organization.Status.ACTIVE, subscription_ends_at__gte=now).count(),
        "expired": qs.filter(
            Q(status=Organization.Status.EXPIRED)
            | Q(status=Organization.Status.ACTIVE, subscription_ends_at__lt=now)
        ).count(),
        "pending": qs.filter(status=Organization.Status.PENDING_PAYMENT).count(),
        "suspended": qs.filter(status=Organization.Status.SUSPENDED).count(),
        "cancelled": qs.filter(status=Organization.Status.CANCELLED).count(),
        "renewal_7_days": qs.filter(
            status=Organization.Status.ACTIVE,
            subscription_ends_at__gte=now,
            subscription_ends_at__lte=renew_soon,
        ).count(),
        "total_users": Users.objects.filter(organization__isnull=False).count(),
        "total_revenue": PaymentOrder.objects.filter(status=PaymentOrder.Status.PAID).count(),
    }


@platform_superuser_required
def platform_dashboard(request):
    stats = _org_stats()
    upcoming_renewals = (
        Organization.objects.filter(
            status=Organization.Status.ACTIVE,
            subscription_ends_at__isnull=False,
        )
        .select_related("plan", "owner")
        .order_by("subscription_ends_at")[:15]
    )
    recent_orgs = Organization.objects.select_related("plan", "owner").order_by("-created_at")[:10]
    recent_payments = PaymentOrder.objects.filter(status=PaymentOrder.Status.PAID).select_related(
        "organization", "plan"
    ).order_by("-paid_at")[:10]
    plans = SubscriptionPlan.objects.order_by("sort_order")

    return render(
        request,
        "saas/platform/dashboard.html",
        {
            "stats": stats,
            "upcoming_renewals": upcoming_renewals,
            "recent_orgs": recent_orgs,
            "recent_payments": recent_payments,
            "plans": plans,
        },
    )


@platform_superuser_required
def platform_organizations(request):
    status_filter = (request.GET.get("status") or "all").strip().lower()
    qs = Organization.objects.select_related("plan", "owner").annotate(
        member_count=Count("memberships")
    )
    if status_filter == "active":
        now = timezone.now()
        qs = qs.filter(status=Organization.Status.ACTIVE, subscription_ends_at__gte=now)
    elif status_filter == "expired":
        now = timezone.now()
        qs = qs.filter(
            Q(status=Organization.Status.EXPIRED)
            | Q(status=Organization.Status.ACTIVE, subscription_ends_at__lt=now)
        )
    elif status_filter in dict(Organization.Status.choices):
        qs = qs.filter(status=status_filter)

    search = (request.GET.get("q") or "").strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(owner__email__icontains=search))

    return render(
        request,
        "saas/platform/organizations.html",
        {
            "organizations": qs.order_by("-created_at"),
            "status_filter": status_filter,
            "search": search,
            "stats": _org_stats(),
        },
    )


@platform_superuser_required
def platform_organization_detail(request, org_id):
    org = get_object_or_404(
        Organization.objects.select_related("plan", "owner"),
        org_id=org_id,
    )
    members = OrganizationMembership.objects.filter(organization=org).select_related("user")
    payments = org.payment_orders.select_related("plan").order_by("-created_at")[:20]
    status_form = OrganizationStatusForm(instance=org)
    extend_form = ExtendRenewalForm()

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "update_status":
            status_form = OrganizationStatusForm(request.POST, instance=org)
            if status_form.is_valid():
                status_form.save()
                messages.success(request, f"Updated {org.name} status and plan.")
                return redirect("platform_organization_detail", org_id=org.org_id)

        elif action == "activate":
            plan = org.plan or SubscriptionPlan.objects.filter(is_active=True).first()
            if plan:
                org.activate_subscription(plan)
                from saas.services import promote_org_owner_to_admin
                promote_org_owner_to_admin(org)
                messages.success(request, f"{org.name} activated on {plan.name} plan with full CRM access.")
            return redirect("platform_organization_detail", org_id=org.org_id)

        elif action == "suspend":
            org.status = Organization.Status.SUSPENDED
            org.save(update_fields=["status", "updated_at"])
            messages.warning(request, f"{org.name} suspended.")
            return redirect("platform_organization_detail", org_id=org.org_id)

        elif action == "extend":
            extend_form = ExtendRenewalForm(request.POST)
            if extend_form.is_valid():
                days = extend_form.cleaned_data["extra_days"]
                base = org.subscription_ends_at or timezone.now()
                if base < timezone.now():
                    base = timezone.now()
                org.subscription_ends_at = base + timedelta(days=days)
                org.status = Organization.Status.ACTIVE
                org.save(update_fields=["subscription_ends_at", "status", "updated_at"])
                messages.success(request, f"Extended {org.name} by {days} days.")
                return redirect("platform_organization_detail", org_id=org.org_id)

    return render(
        request,
        "saas/platform/organization_detail.html",
        {
            "org": org,
            "members": members,
            "payments": payments,
            "status_form": status_form,
            "extend_form": extend_form,
        },
    )


@platform_superuser_required
def platform_plans(request):
    plans = SubscriptionPlan.objects.order_by("sort_order")

    if request.method == "POST":
        plan_id = request.POST.get("plan_id")
        plan = get_object_or_404(SubscriptionPlan, plan_id=plan_id)
        form = SubscriptionPlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, f"Updated {plan.name} pricing and features.")
            return redirect("platform_plans")
        messages.error(request, "Could not save plan. Check the form errors.")
        plan_forms = [(p, form if p.plan_id == plan.plan_id else SubscriptionPlanForm(instance=p)) for p in plans]
    else:
        plan_forms = [(p, SubscriptionPlanForm(instance=p)) for p in plans]

    return render(
        request,
        "saas/platform/plans.html",
        {"plan_forms": plan_forms},
    )


@platform_superuser_required
def platform_payments(request):
    payments = PaymentOrder.objects.select_related("organization", "plan").order_by("-created_at")[:100]
    paid_total = PaymentOrder.objects.filter(status=PaymentOrder.Status.PAID)
    return render(
        request,
        "saas/platform/payments.html",
        {
            "payments": payments,
            "paid_count": paid_total.count(),
        },
    )


@platform_superuser_required
def platform_users(request):
    users = Users.objects.select_related("organization").order_by("-date_joined")[:200]
    return render(request, "saas/platform/users.html", {"users": users, "stats": _org_stats()})
