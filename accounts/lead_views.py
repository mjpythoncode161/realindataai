from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .activity_logger import log_activity
from .forms import LeadActivityForm, LeadConfirmForm, LeadForm
from .lead_services import convert_lead_to_customer, phone_has_project_booking
from .models import ActivityLog, Lead, LeadActivity, Users, users_with_any_role_query, users_with_role_query


LEAD_MANAGEMENT_ROLES = ("followup", "admin", "manager", "executive", "telecaller")
LEAD_ASSIGNABLE_ROLES = ("followup", "manager", "executive", "telecaller")


def _can_manage_leads(user):
    return user.has_any_role(*LEAD_MANAGEMENT_ROLES)


def _team_user_ids(user):
    return Users.objects.filter(created_by=user).values_list("pk", flat=True)


def _lead_queryset_for(user):
    from django.db.models import Q
    from saas.tenant import get_user_organization

    org = get_user_organization(user)
    qs = Lead.objects.select_related("p_id", "assigned_to", "created_by", "converted_customer__u_id")
    if org:
        qs = qs.filter(Q(organization=org) | Q(p_id__organization=org)).distinct()
    elif not getattr(user, "is_superuser", False):
        return qs.none()

    if user.has_role("admin"):
        return qs
    if user.has_role("manager"):
        team_ids = list(_team_user_ids(user))
        return qs.filter(
            Q(assigned_to=user)
            | Q(created_by=user)
            | Q(assigned_to_id__in=team_ids)
            | Q(created_by_id__in=team_ids)
        )
    return qs.filter(Q(assigned_to=user) | Q(created_by=user))


@login_required
def lead_list(request):
    if not _can_manage_leads(request.user):
        return HttpResponseForbidden("Access denied.")

    status = (request.GET.get("status") or "open").strip()
    qs = _lead_queryset_for(request.user).distinct()

    if status == "open":
        qs = qs.exclude(status__in=[Lead.Status.CONFIRMED, Lead.Status.CLOSED_LOST])
    elif status != "all":
        qs = qs.filter(status=status)

    counts = {
        "total": _lead_queryset_for(request.user).distinct().count(),
        "pending": _lead_queryset_for(request.user).exclude(
            status__in=[Lead.Status.CONFIRMED, Lead.Status.CLOSED_LOST]
        ).distinct().count(),
        "confirmed": _lead_queryset_for(request.user).filter(status=Lead.Status.CONFIRMED).distinct().count(),
        "closed": _lead_queryset_for(request.user).filter(status=Lead.Status.CLOSED_LOST).distinct().count(),
    }

    return render(
        request,
        "accounts/lead_list.html",
        {
            "leads": qs,
            "status_filter": status,
            "counts": counts,
            "status_choices": Lead.Status.choices,
        },
    )


@login_required
def lead_add(request):
    if not _can_manage_leads(request.user):
        return HttpResponseForbidden("Access denied.")

    if request.method == "POST":
        form = LeadForm(request.POST, user=request.user)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.created_by = request.user
            from saas.tenant import get_request_organization
            org = get_request_organization(request)
            if org:
                lead.organization = org
            if not lead.assigned_to_id and not (
                request.user.has_role("manager") and not request.user.has_role("admin")
            ):
                lead.assigned_to = request.user
            lead.save()
            if lead.notes:
                LeadActivity.objects.create(
                    lead=lead,
                    activity_type=LeadActivity.ActivityType.NOTE,
                    note=lead.notes,
                    next_follow_up_date=lead.next_follow_up_date,
                    created_by=request.user,
                )
            messages.success(request, f"Lead added for {lead.full_name}.")
            log_activity(request.user, ActivityLog.Action.CREATE, "Lead",
                         lead.lead_id, lead.full_name, f"Phone: {lead.phone}")
            return redirect("lead_detail", lead_id=lead.lead_id)
        messages.error(request, "Please correct the errors below.")
    else:
        initial = {"status": Lead.Status.NEW}
        if not (request.user.has_role("manager") and not request.user.has_role("admin")):
            initial["assigned_to"] = request.user.pk
        form = LeadForm(initial=initial, user=request.user)

    return render(request, "accounts/lead_form.html", {"form": form, "page_title": "Add Lead"})


@login_required
def lead_edit(request, lead_id: int):
    if not _can_manage_leads(request.user):
        return HttpResponseForbidden("Access denied.")

    lead = get_object_or_404(_lead_queryset_for(request.user).distinct(), pk=lead_id)
    if not lead.is_open:
        messages.warning(request, "This lead is closed and cannot be edited.")
        return redirect("lead_detail", lead_id=lead.lead_id)

    if request.method == "POST":
        form = LeadForm(request.POST, instance=lead, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Lead updated.")
            log_activity(request.user, ActivityLog.Action.EDIT, "Lead",
                         lead.lead_id, lead.full_name, "Lead details updated.")
            return redirect("lead_detail", lead_id=lead.lead_id)
        messages.error(request, "Please correct the errors below.")
    else:
        form = LeadForm(instance=lead, user=request.user)

    return render(
        request,
        "accounts/lead_form.html",
        {"form": form, "page_title": "Edit Lead", "lead": lead},
    )


@login_required
def lead_detail(request, lead_id: int):
    if not _can_manage_leads(request.user):
        return HttpResponseForbidden("Access denied.")

    lead = get_object_or_404(
        _lead_queryset_for(request.user).prefetch_related("activities__created_by").distinct(),
        pk=lead_id,
    )
    activity_form = LeadActivityForm()

    if request.method == "POST" and lead.is_open:
        activity_form = LeadActivityForm(request.POST)
        if activity_form.is_valid():
            activity = activity_form.save(commit=False)
            activity.lead = lead
            activity.created_by = request.user
            activity.save()
            if activity.next_follow_up_date:
                lead.next_follow_up_date = activity.next_follow_up_date
                lead.save(update_fields=["next_follow_up_date", "updated_at"])
            messages.success(request, "Follow-up activity saved.")
            return redirect("lead_detail", lead_id=lead.lead_id)

    return render(
        request,
        "accounts/lead_detail.html",
        {
            "lead": lead,
            "activity_form": activity_form,
            "activities": lead.activities.all(),
        },
    )


@login_required
@transaction.atomic
def lead_confirm(request, lead_id: int):
    if not _can_manage_leads(request.user):
        return HttpResponseForbidden("Access denied.")

    lead = get_object_or_404(_lead_queryset_for(request.user).distinct(), pk=lead_id)
    if lead.status == Lead.Status.CONFIRMED:
        messages.info(request, "Lead is already confirmed and converted to customer.")
        return redirect("lead_detail", lead_id=lead.lead_id)

    if request.method == "POST":
        form = LeadConfirmForm(request.POST)
        if form.is_valid():
            try:
                customer = convert_lead_to_customer(
                    lead,
                    request.user,
                    password=form.cleaned_data.get("password") or None,
                )
                LeadActivity.objects.create(
                    lead=lead,
                    activity_type=LeadActivity.ActivityType.STATUS,
                    note="Lead confirmed and converted to customer.",
                    created_by=request.user,
                )
                messages.success(
                    request,
                    f"Lead confirmed. Customer {customer.full_name} is now in the Customers section.",
                )
                log_activity(request.user, ActivityLog.Action.STATUS, "Lead",
                             lead.lead_id, lead.full_name, "Confirmed → converted to customer.")
                if request.user.has_role("admin"):
                    return redirect("customer_list")
                return redirect("lead_list")
            except ValueError as exc:
                messages.error(request, str(exc))
    else:
        form = LeadConfirmForm()

    return render(
        request,
        "accounts/lead_confirm.html",
        {"lead": lead, "form": form},
    )


@login_required
@transaction.atomic
def lead_close_lost(request, lead_id: int):
    if not _can_manage_leads(request.user):
        return HttpResponseForbidden("Access denied.")

    lead = get_object_or_404(_lead_queryset_for(request.user).distinct(), pk=lead_id)
    if not lead.is_open:
        return redirect("lead_detail", lead_id=lead.lead_id)

    if request.method == "POST":
        reason = (request.POST.get("reason") or "").strip() or "Lead closed without conversion."
        lead.status = Lead.Status.CLOSED_LOST
        lead.closed_at = timezone.now()
        lead.save(update_fields=["status", "closed_at", "updated_at"])
        LeadActivity.objects.create(
            lead=lead,
            activity_type=LeadActivity.ActivityType.STATUS,
            note=reason,
            created_by=request.user,
        )
        messages.success(request, "Lead marked as closed (lost).")
        log_activity(request.user, ActivityLog.Action.STATUS, "Lead",
                     lead.lead_id, lead.full_name, f"Closed (lost). Reason: {reason}")
        return redirect("lead_list")

    return render(request, "accounts/lead_close.html", {"lead": lead})


@login_required
def activity_edit(request, activity_id: int):
    if not _can_manage_leads(request.user):
        return HttpResponseForbidden("Access denied.")

    activity = get_object_or_404(LeadActivity, pk=activity_id)
    lead = activity.lead

    # Only allow edit by the creator, or admin/manager
    if not (request.user.has_any_role("admin", "manager") or activity.created_by == request.user):
        return HttpResponseForbidden("You can only edit your own activities.")

    if request.method == "POST":
        from .forms import LeadActivityForm
        form = LeadActivityForm(request.POST, instance=activity)
        if form.is_valid():
            form.save()
            messages.success(request, "Activity updated.")
            log_activity(request.user, ActivityLog.Action.EDIT, "Lead Activity",
                         activity.activity_id, str(lead.full_name),
                         f"Type: {activity.activity_type}")
        else:
            messages.error(request, "Could not update activity.")
    return redirect("lead_detail", lead_id=lead.lead_id)


@login_required
def activity_delete(request, activity_id: int):
    if not _can_manage_leads(request.user):
        return HttpResponseForbidden("Access denied.")

    activity = get_object_or_404(LeadActivity, pk=activity_id)
    lead = activity.lead

    # Only allow delete by the creator, or admin/manager
    if not (request.user.has_any_role("admin", "manager") or activity.created_by == request.user):
        return HttpResponseForbidden("You can only delete your own activities.")

    if request.method == "POST":
        repr_str = f"{lead.full_name} — {activity.get_activity_type_display()}"
        activity.delete()
        messages.success(request, "Activity deleted.")
        log_activity(request.user, ActivityLog.Action.DELETE, "Lead Activity",
                     activity_id, repr_str, "Activity deleted.")
    return redirect("lead_detail", lead_id=lead.lead_id)


@login_required
def lead_check_booking(request):
    if not _can_manage_leads(request.user):
        return JsonResponse({"exists": False})

    phone = request.GET.get("phone", "")
    project_id = request.GET.get("p_id") or request.GET.get("project_id")
    if not project_id:
        return JsonResponse({"exists": False})

    exists = phone_has_project_booking(phone, project_id)
    return JsonResponse(
        {
            "exists": exists,
            "message": "Already booking exists for this customer on the selected project.",
        }
    )
