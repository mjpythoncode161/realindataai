"""Lead management reports — each report supports from_date / to_date filters."""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import render

from .lead_views import _can_manage_leads, _lead_queryset_for
from .models import Lead, LeadActivity, users_with_any_role_query


def _guard(request):
    if not _can_manage_leads(request.user):
        return HttpResponseForbidden("Access denied.")
    return None


def _dates(request):
    return (request.GET.get("from_date") or "").strip(), (request.GET.get("to_date") or "").strip()


def _base_qs(user):
    return _lead_queryset_for(user).distinct()


def _by_created(qs, from_date, to_date):
    if from_date:
        qs = qs.filter(created_at__date__gte=from_date)
    if to_date:
        qs = qs.filter(created_at__date__lte=to_date)
    return qs


def _ctx(request, title, **extra):
    from_date, to_date = _dates(request)
    return {
        "page_title": title,
        "from_date": from_date,
        "to_date": to_date,
        **extra,
    }


@login_required
def lead_reports_hub(request):
    denied = _guard(request)
    if denied:
        return denied
    return render(request, "accounts/lead_reports/hub.html", _ctx(request, "Lead Reports"))


@login_required
def lead_summary_report(request):
    denied = _guard(request)
    if denied:
        return denied
    from_date, to_date = _dates(request)
    qs = _by_created(_base_qs(request.user), from_date, to_date)
    summary = {
        "total": qs.count(),
        "new": qs.filter(status=Lead.Status.NEW).count(),
        "contacted": qs.filter(status=Lead.Status.CONTACTED).count(),
        "in_progress": qs.filter(status=Lead.Status.IN_PROGRESS).count(),
        "confirmed": qs.filter(status=Lead.Status.CONFIRMED).count(),
        "closed": qs.filter(status=Lead.Status.CLOSED_LOST).count(),
        "open": qs.exclude(status__in=[Lead.Status.CONFIRMED, Lead.Status.CLOSED_LOST]).count(),
    }
    return render(
        request,
        "accounts/lead_reports/summary.html",
        _ctx(
            request,
            "Lead Summary Report",
            leads=qs.order_by("-created_at"),
            summary=summary,
        ),
    )


@login_required
def lead_status_report(request):
    denied = _guard(request)
    if denied:
        return denied
    from_date, to_date = _dates(request)
    status = (request.GET.get("status") or "").strip()
    qs = _by_created(_base_qs(request.user), from_date, to_date)
    if status:
        qs = qs.filter(status=status)
    rows = []
    for code, label in Lead.Status.choices:
        count = qs.filter(status=code).count()
        if count or status == code or not status:
            rows.append({"code": code, "label": label, "count": count})
    return render(
        request,
        "accounts/lead_reports/status.html",
        _ctx(
            request,
            "Lead Status Report",
            leads=qs.order_by("-created_at"),
            status_filter=status,
            status_choices=Lead.Status.choices,
            status_rows=rows,
        ),
    )


@login_required
def lead_source_report(request):
    denied = _guard(request)
    if denied:
        return denied
    from_date, to_date = _dates(request)
    qs = _by_created(_base_qs(request.user), from_date, to_date)
    source_map = dict(Lead.Source.choices)
    counts = qs.values("source").annotate(count=Count("lead_id")).order_by("-count")
    rows = [
        {"code": r["source"], "label": source_map.get(r["source"], r["source"]), "count": r["count"]}
        for r in counts
    ]
    return render(
        request,
        "accounts/lead_reports/source.html",
        _ctx(request, "Lead Source Report", leads=qs.order_by("-created_at"), source_rows=rows),
    )


@login_required
def lead_project_report(request):
    denied = _guard(request)
    if denied:
        return denied
    from_date, to_date = _dates(request)
    project_id = (request.GET.get("project") or "").strip()
    qs = _by_created(_base_qs(request.user), from_date, to_date)
    if project_id == "none":
        qs = qs.filter(p_id__isnull=True)
    elif project_id:
        qs = qs.filter(p_id_id=project_id)
    from saas.tenant import tenant_projects

    projects = tenant_projects(request).order_by("name")
    rows = []
    for proj in projects:
        cnt = qs.filter(p_id=proj).count()
        if cnt or str(proj.p_id) == project_id:
            rows.append({"project": proj, "count": cnt})
    unassigned = qs.filter(p_id__isnull=True).count()
    if unassigned or project_id == "none":
        rows.append({"project": None, "count": unassigned, "label": "No Project"})
    return render(
        request,
        "accounts/lead_reports/project.html",
        _ctx(
            request,
            "Lead Project Report",
            leads=qs.select_related("p_id").order_by("-created_at"),
            project_rows=rows,
            project_filter=project_id,
            projects=projects,
        ),
    )


@login_required
def lead_staff_report(request):
    denied = _guard(request)
    if denied:
        return denied
    from_date, to_date = _dates(request)
    staff_id = (request.GET.get("staff") or "").strip()
    qs = _by_created(_base_qs(request.user), from_date, to_date)
    if staff_id == "none":
        qs = qs.filter(assigned_to__isnull=True)
    elif staff_id:
        qs = qs.filter(assigned_to_id=staff_id)
    from saas.tenant import tenant_staff_users

    staff_qs = tenant_staff_users(request).filter(
        users_with_any_role_query("manager", "executive", "telecaller", "followup", "admin")
    ).distinct()

    rows = []
    for user in staff_qs.order_by("full_name"):
        cnt = qs.filter(assigned_to=user).count()
        if cnt or str(user.pk) == staff_id:
            rows.append({"user": user, "count": cnt})
    unassigned = qs.filter(assigned_to__isnull=True).count()
    if unassigned or staff_id == "none":
        rows.append({"user": None, "count": unassigned, "label": "Unassigned"})
    return render(
        request,
        "accounts/lead_reports/staff.html",
        _ctx(
            request,
            "Lead Staff Report",
            leads=qs.select_related("assigned_to").order_by("-created_at"),
            staff_rows=rows,
            staff_filter=staff_id,
            staff_users=staff_qs.order_by("full_name"),
        ),
    )


@login_required
def lead_conversion_report(request):
    denied = _guard(request)
    if denied:
        return denied
    from_date, to_date = _dates(request)
    base = _base_qs(request.user)
    confirmed_qs = base.filter(status=Lead.Status.CONFIRMED)
    closed_qs = base.filter(status=Lead.Status.CLOSED_LOST)
    if from_date:
        confirmed_qs = confirmed_qs.filter(
            Q(confirmed_at__date__gte=from_date) | Q(confirmed_at__isnull=True, created_at__date__gte=from_date)
        )
        closed_qs = closed_qs.filter(
            Q(closed_at__date__gte=from_date) | Q(closed_at__isnull=True, created_at__date__gte=from_date)
        )
    if to_date:
        confirmed_qs = confirmed_qs.filter(
            Q(confirmed_at__date__lte=to_date) | Q(confirmed_at__isnull=True, created_at__date__lte=to_date)
        )
        closed_qs = closed_qs.filter(
            Q(closed_at__date__lte=to_date) | Q(closed_at__isnull=True, created_at__date__lte=to_date)
        )
    confirmed_count = confirmed_qs.count()
    closed_count = closed_qs.count()
    total_outcome = confirmed_count + closed_count
    conversion_rate = round((confirmed_count / total_outcome * 100), 1) if total_outcome else 0
    return render(
        request,
        "accounts/lead_reports/conversion.html",
        _ctx(
            request,
            "Lead Conversion Report",
            confirmed_leads=confirmed_qs.order_by("-confirmed_at", "-created_at"),
            closed_leads=closed_qs.order_by("-closed_at", "-created_at"),
            confirmed_count=confirmed_count,
            closed_count=closed_count,
            conversion_rate=conversion_rate,
        ),
    )


@login_required
def lead_followup_report(request):
    denied = _guard(request)
    if denied:
        return denied
    from_date, to_date = _dates(request)
    qs = _base_qs(request.user).exclude(
        status__in=[Lead.Status.CONFIRMED, Lead.Status.CLOSED_LOST]
    )
    if from_date:
        qs = qs.filter(next_follow_up_date__gte=from_date)
    if to_date:
        qs = qs.filter(next_follow_up_date__lte=to_date)
    return render(
        request,
        "accounts/lead_reports/followup.html",
        _ctx(
            request,
            "Lead Follow-up Report",
            leads=qs.select_related("p_id", "assigned_to").order_by("next_follow_up_date", "-created_at"),
            total_followups=qs.count(),
        ),
    )


@login_required
def lead_activity_report(request):
    denied = _guard(request)
    if denied:
        return denied
    from_date, to_date = _dates(request)
    lead_ids = _base_qs(request.user).values_list("lead_id", flat=True)
    qs = LeadActivity.objects.filter(lead_id__in=lead_ids).select_related(
        "lead", "created_by"
    )
    if from_date:
        qs = qs.filter(created_at__date__gte=from_date)
    if to_date:
        qs = qs.filter(created_at__date__lte=to_date)
    type_rows = qs.values("activity_type").annotate(count=Count("activity_id")).order_by("-count")
    type_map = dict(LeadActivity.ActivityType.choices)
    return render(
        request,
        "accounts/lead_reports/activity.html",
        _ctx(
            request,
            "Lead Activity Report",
            activities=qs.order_by("-created_at"),
            activity_rows=[
                {"code": r["activity_type"], "label": type_map.get(r["activity_type"], r["activity_type"]), "count": r["count"]}
                for r in type_rows
            ],
            total_activities=qs.count(),
        ),
    )
