from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from accounts.activity_logger import log_activity
from accounts.models import ActivityLog

from .forms import (
    ACCOUNTS_PAYMENT_FORMSET_PREFIX,
    AccountsDebitPaymentFormSet,
    BookingItemFormSet,
    BookingPlotSwapForm,
    BookingMasterForm,
    ProjectForm,
    BookingAgentSettingsForm,
    AgentMasterForm,
    ReceiptMasterForm,
    PaymentForm,
)
from .models import (
    AgentMaster,
    BalanceMaster,
    BookingItem,
    BookingMaster,
    IncentiveWithdrawalRequest,
    Payment,
    Project,
    ReceiptMaster,
    get_booking_agent_settings,
)


def format_form_errors(form, formset=None):
    error_list = []
    if form and form.errors:
        for field, errors in form.errors.items():
            if field == "__all__":
                error_list.append(f"<b>General:</b> {', '.join(errors)}")
            else:
                label = form.fields[field].label or field.replace("_", " ").capitalize() if field in form.fields else field.replace("_", " ").capitalize()
                if field in ("bi_id", "id"):
                    label = "Item"
                error_list.append(f"<b>{label}:</b> {', '.join(errors)}")
    if formset:
        for i, f_errors in enumerate(formset.errors):
            if f_errors:
                for field, errors in f_errors.items():
                    label = field.replace("_", " ").capitalize()
                    if field in ("bi_id", "id"):
                        label = "Item"
                    if i < len(formset.forms):
                        f = formset.forms[i]
                        if field in f.fields:
                            label = f.fields[field].label or label
                    error_list.append(f"<b>Item {i+1} - {label}:</b> {', '.join(errors)}")
        for error in formset.non_form_errors():
            error_list.append(f"<b>Items:</b> {error}")
    return "<br>".join(error_list) if error_list else "Please check the form for errors."


def _booking_form_context(request, **extra):
    """Shared context for booking form — projects scoped to tenant."""
    from saas.tenant import tenant_projects

    projects = tenant_projects(request).order_by("name")
    context = {
        "projects": projects,
        "projects_json": json.dumps(
            {
                str(p.p_id): {
                    "name": p.name,
                    "location": p.location or "",
                    "num_plots": p.num_plots,
                }
                for p in projects
            }
        ),
    }
    context.update(extra)
    return context


@login_required
def booking_list(request):
    from saas.tenant import tenant_bookings

    if request.user.has_role("accounts"):
        return HttpResponseForbidden("Accounts cannot access Bookings.")

    bookings = (
        tenant_bookings(request)
        .exclude(status="CANCELLED")
        .select_related("p_id")
        .prefetch_related("items")
        .order_by("-b_id")
    )
    if request.user.has_role("manager") and not request.user.has_role("admin"):
        bookings = bookings.filter(created_by=request.user)
    elif request.user.has_role("customer"):
        bookings = bookings.filter(u_id=request.user)

    return render(request, "bookings/booking_list.html", {"bookings": bookings})


@login_required
@transaction.atomic
def booking_create(request):
    if request.user.has_any_role("accounts", "followup"):
        return HttpResponseForbidden("You do not have permission to create bookings.")
        
    if request.method == "POST":
        form = BookingMasterForm(request.POST, user=request.user)
        formset = BookingItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            from saas.tenant import get_request_organization

            booking = form.save(commit=False)
            booking.created_by = request.user
            org = get_request_organization(request)
            if org:
                booking.organization = org
            
            user = sync_customer_from_booking(booking)
            if user:
                booking.u_id = user

            # Enforce FULL payment logic
            if booking.payment_status == BookingMaster.PaymentStatus.FULL:
                from datetime import date, timedelta
                booking.next_payment_date = date.today() + timedelta(days=30)
            
            # Sync agent TDS/security from profile; commission % stays from the booking form.
            from .models import AgentMaster
            if booking.manager_u_id:
                agent = AgentMaster.objects.filter(u_id=booking.manager_u_id, role='manager').first()
                if agent:
                    booking.manager_tds = agent.tds_amount
                    booking.manager_security_amount = agent.security_amount
            if booking.executive_u_id:
                agent = AgentMaster.objects.filter(u_id=booking.executive_u_id, role='executive').first()
                if agent:
                    booking.executive_tds = agent.tds_amount
                    booking.executive_security_amount = agent.security_amount
            if booking.telecaller_u_id:
                agent = AgentMaster.objects.filter(u_id=booking.telecaller_u_id, role='telecaller').first()
                if agent:
                    booking.telecaller_tds = agent.tds_amount
                    booking.telecaller_security_amount = agent.security_amount

            booking.save()
            formset.instance = booking
            formset.save()

            balance, _ = BalanceMaster.objects.get_or_create(b_id=booking)
            balance.recalculate()
            balance.save()

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "success", "message": f"Booking created (Booking ID: {booking.b_id})."})
            messages.success(request, f"Booking created (Booking ID: {booking.b_id}).")
            return redirect("booking_list")

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": format_form_errors(form, formset)})
        messages.error(request, "Please correct the errors and try again.")
    else:
        form = BookingMasterForm(user=request.user)
        formset = BookingItemFormSet(prefix="items")

    return render(
        request,
        "bookings/booking_form.html",
        _booking_form_context(
            request,
            form=form,
            formset=formset,
            page_title="Site BookingMaster Application",
        ),
    )


@login_required
@transaction.atomic
def booking_edit(request, b_id: int):
    from saas.tenant import tenant_bookings

    booking = get_object_or_404(tenant_bookings(request), pk=b_id)

    if request.method == "POST":
        # Capture old item values BEFORE form saves them
        old_items_snapshot = {
            item.pk: {"rate": item.rate, "area": item.area_sqft, "plot": item.plot_number}
            for item in booking.items.all()
        }

        form = BookingMasterForm(request.POST, instance=booking, user=request.user)
        formset = BookingItemFormSet(
            request.POST,
            instance=booking,
            prefix="items",
        )

        if form.is_valid() and formset.is_valid():
            # Strict Server-side Plot Validation
            submitted_plots = []
            for item_form in formset:
                if item_form.cleaned_data and not item_form.cleaned_data.get('DELETE'):
                    plot_str = item_form.cleaned_data.get('plot_number', '')
                    if plot_str:
                        plots = [p.strip() for p in plot_str.split(',') if p.strip()]
                        submitted_plots.extend(plots)
            
            # Debug Check
            current_booking_id = booking.b_id
            print("Current Booking ID:", current_booking_id)
            
            already_booked = []
            master_project = form.cleaned_data.get("p_id")
            for item_form in formset:
                if item_form.cleaned_data and not item_form.cleaned_data.get('DELETE'):
                    plot_str = item_form.cleaned_data.get('plot_number', '')
                    project_id = master_project
                    
                    if plot_str and project_id:
                        plots = [p.strip() for p in plot_str.split(',') if p.strip()]
                        for plot in plots:
                            from django.db.models import Q
                            exists_elsewhere = BookingItem.objects.filter(
                                p_id=project_id
                            ).filter(
                                Q(plot_number=plot) | 
                                Q(plot_number__startswith=plot+",") | 
                                Q(plot_number__contains=","+plot+",") | 
                                Q(plot_number__endswith=","+plot)
                            ).exclude(b_id_id=current_booking_id).exists()
                            
                            if exists_elsewhere:
                                already_booked.append(f"{plot} ({project_id.name})")
            
            if already_booked:
                msg = f"Plot(s) already booked: {', '.join(already_booked)}"
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"status": "error", "message": msg})
                messages.error(request, msg)
                return render(
                    request,
                    "bookings/booking_form.html",
                    _booking_form_context(
                        request,
                        form=form,
                        formset=formset,
                        page_title="Edit Booking",
                        booking=booking,
                    ),
                )

            booking = form.save(commit=False)
            
            user = sync_customer_from_booking(booking)
            booking.u_id = user

            # Enforce FULL payment logic
            if booking.payment_status == BookingMaster.PaymentStatus.FULL:
                from datetime import date, timedelta
                booking.next_payment_date = date.today() + timedelta(days=30)

            # Sync agent TDS/security from profile; commission % stays from the booking form.
            from .models import AgentMaster
            if booking.manager_u_id:
                agent = AgentMaster.objects.filter(u_id=booking.manager_u_id, role='manager').first()
                if agent:
                    booking.manager_tds = agent.tds_amount
                    booking.manager_security_amount = agent.security_amount
            if booking.executive_u_id:
                agent = AgentMaster.objects.filter(u_id=booking.executive_u_id, role='executive').first()
                if agent:
                    booking.executive_tds = agent.tds_amount
                    booking.executive_security_amount = agent.security_amount
            if booking.telecaller_u_id:
                agent = AgentMaster.objects.filter(u_id=booking.telecaller_u_id, role='telecaller').first()
                if agent:
                    booking.telecaller_tds = agent.tds_amount
                    booking.telecaller_security_amount = agent.security_amount

            booking.save()
            formset.save()

            balance, _ = BalanceMaster.objects.get_or_create(b_id=booking)
            balance.recalculate()
            balance.save()

            # Capture change details for log
            item_changes = []
            for it in booking.items.all():
                old = old_items_snapshot.get(it.pk, {})
                rate_info = f"Rate: {old.get('rate','?')} -> {it.rate}" if old.get("rate") != it.rate else f"Rate: {it.rate}"
                area_info = f"Area: {old.get('area','?')} -> {it.area_sqft}" if old.get("area") != it.area_sqft else f"Area: {it.area_sqft}"
                item_changes.append(f"Plot {it.plot_number} | {rate_info} | {area_info} | Total: {it.total_amount}")
            project_name = booking.p_id.name if booking.p_id else "N/A"
            changes_str = (
                f"Customer: {booking.full_name} | Project: {project_name} | "
                f"Status: {booking.payment_status} | Total: {balance.total_amount} | "
                f"Paid: {balance.paid_amount} | Balance: {balance.balance_amount}"
                + (" | " + "; ".join(item_changes) if item_changes else "")
            )
            log_activity(request.user, ActivityLog.Action.EDIT, "Booking",
                         booking.b_id, booking.booking_no, changes_str)

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "success", "message": f"Booking updated (Booking ID: {booking.b_id})."})
            messages.success(request, f"Booking updated (Booking ID: {booking.b_id}).")
            return redirect("booking_list")

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": format_form_errors(form, formset)})
        messages.error(request, "Please correct the errors and try again.")
    else:
        form = BookingMasterForm(instance=booking, user=request.user)
        formset = BookingItemFormSet(instance=booking, prefix="items")

    return render(
        request,
        "bookings/booking_form.html",
        _booking_form_context(
            request,
            form=form,
            formset=formset,
            booking=booking,
            page_title="Edit BookingMaster Application",
        ),
    )


@login_required
def booking_view(request, b_id: int):
    from .models import get_booking_agent_settings
    from .share_utils import build_booking_share

    booking = (
        BookingMaster.objects.select_related("p_id", "u_id", "balance")
        .prefetch_related("items")
        .get(pk=b_id)
    )
    company_name = get_booking_agent_settings().company_name or "LANDLINK REAL ESTATE"
    share = build_booking_share(request, booking, company_name)
    return render(
        request,
        "bookings/booking_view.html",
        {
            "booking": booking,
            "share": share,
            "send_email_url": reverse("booking_share_email", kwargs={"b_id": b_id}),
        },
    )


@login_required
def booking_client_copy(request, b_id: int):
    """Client-facing booking copy — no manager/executive/telecaller commission details."""
    from .models import get_booking_agent_settings
    from .share_utils import build_booking_share

    booking = (
        BookingMaster.objects.select_related("p_id", "u_id", "balance")
        .prefetch_related("items")
        .get(pk=b_id)
    )
    company_name = get_booking_agent_settings().company_name or "LANDLINK REAL ESTATE"
    share = build_booking_share(request, booking, company_name)
    return render(
        request,
        "bookings/booking_client_copy.html",
        {
            "booking": booking,
            "share": share,
            "send_email_url": reverse("booking_share_email", kwargs={"b_id": b_id}),
        },
    )


@login_required
@require_POST
def booking_share_email(request, b_id: int):
    from .models import get_booking_agent_settings
    from .share_utils import booking_share_text, send_customer_email

    booking = (
        BookingMaster.objects.select_related("p_id", "balance")
        .prefetch_related("items")
        .get(pk=b_id)
    )
    company_name = get_booking_agent_settings().company_name or "LANDLINK REAL ESTATE"
    client_copy_url = request.build_absolute_uri(
        reverse("booking_client_copy", kwargs={"b_id": booking.b_id})
    )
    to_email = (request.POST.get("email") or booking.customer_email or "").strip()
    if not to_email:
        return JsonResponse(
            {"status": "error", "message": "No customer email address on this booking."}
        )
    subject, body = booking_share_text(booking, company_name, client_copy_url)
    try:
        send_customer_email(to_email, subject, body)
        return JsonResponse(
            {"status": "success", "message": f"Booking details sent to {to_email}."}
        )
    except Exception as exc:
        return JsonResponse({"status": "error", "message": str(exc)})


@login_required
@require_POST
def receipt_share_email(request, rm_id: int):
    from .models import get_booking_agent_settings
    from .share_utils import receipt_share_text, send_customer_email

    receipt = get_object_or_404(
        ReceiptMaster.objects.select_related("b_id", "b_id__u_id"), pk=rm_id
    )
    company_name = get_booking_agent_settings().company_name or "LANDLINK REAL ESTATE"
    to_email = (request.POST.get("email") or "").strip()
    if not to_email and receipt.b_id:
        to_email = (receipt.b_id.customer_email or "").strip()
    if not to_email:
        return JsonResponse(
            {"status": "error", "message": "No customer email address for this receipt."}
        )
    subject, body = receipt_share_text(receipt, company_name)
    try:
        send_customer_email(to_email, subject, body)
        return JsonResponse(
            {"status": "success", "message": f"Receipt sent to {to_email}."}
        )
    except Exception as exc:
        return JsonResponse({"status": "error", "message": str(exc)})


@login_required
@require_POST
@transaction.atomic
def booking_mark_kgp(request, b_id: int):
    if request.user.has_any_role("accounts", "customer", "followup"):
        return HttpResponseForbidden("You do not have permission to mark KGP.")

    booking = get_object_or_404(BookingMaster, pk=b_id)
    if booking.status == BookingMaster.BookingStatus.CANCELLED:
        msg = "Cancelled bookings cannot be marked as KGP completed."
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"status": "error", "message": msg})
        messages.error(request, msg)
        return redirect("booking_list")

    if booking.kgp_completed:
        msg = "KGP is already marked as completed for this booking."
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"status": "error", "message": msg})
        messages.info(request, msg)
        return redirect("booking_list")

    from datetime import date

    booking.kgp_completed = True
    booking.kgp_completed_at = date.today()
    booking.save(update_fields=["kgp_completed", "kgp_completed_at"])

    msg = f"KGP (Government Survey) marked complete for booking {booking.booking_no}."
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "success", "message": msg})
    messages.success(request, msg)
    return redirect("booking_list")


def _ensure_booking_item(booking: BookingMaster) -> BookingItem:
    """Ensure booking has at least one item row for KGP edit/swap."""
    item = booking.items.first()
    if item:
        return item
    return BookingItem.objects.create(
        b_id=booking,
        p_id=booking.p_id,
        area_sqft=Decimal("0.00"),
        rate=Decimal("0.00"),
    )


@login_required
def booking_kgp_edit(request, b_id: int):
    """Removed — use normal booking edit for all fields after KGP."""
    return redirect("booking_edit", b_id=b_id)


@login_required
@transaction.atomic
def booking_kgp_swap(request, b_id: int):
    if request.user.has_any_role("accounts", "customer", "followup"):
        return HttpResponseForbidden("You do not have permission to swap plots.")

    booking = get_object_or_404(
        BookingMaster.objects.select_related("p_id").prefetch_related("items"),
        pk=b_id,
    )
    if not booking.kgp_completed:
        messages.error(
            request,
            "Plot/Flat swap is available only after Government Survey (KGP) is marked complete.",
        )
        return redirect("booking_list")

    _ensure_booking_item(booking)
    booking = BookingMaster.objects.select_related("p_id").prefetch_related("items").get(
        pk=booking.pk
    )

    swap_targets = (
        BookingMaster.objects.filter(
            p_id=booking.p_id,
            kgp_completed=True,
            status=BookingMaster.BookingStatus.ACTIVE,
        )
        .exclude(pk=booking.pk)
        .prefetch_related("items")
        .order_by("-b_id")
    )
    current_item = booking.items.first()

    if request.method == "POST":
        form = BookingPlotSwapForm(booking, request.POST)
        if form.is_valid():
            target_booking = form.cleaned_data["swap_with_booking"]
            source_item = BookingItem.objects.get(pk=form.cleaned_data["source_item"].pk)
            target_item = BookingItem.objects.get(pk=form.cleaned_data["target_item"].pk)
            old_source_plot = source_item.plot_number or "-"
            old_target_plot = target_item.plot_number or "-"

            _swap_booking_plot_items(source_item, target_item)
            _recalculate_booking_balance(booking)
            _recalculate_booking_balance(target_booking)

            item = BookingItem.objects.get(pk=source_item.pk)
            msg = (
                f"Plot/Flat No. swapped ({old_source_plot} ↔ {old_target_plot}) with "
                f"{target_booking.booking_no}. "
                f"Your booking now — Plot / Flat No.: {item.plot_number or '-'}, "
                f"Area (sq.ft): {item.area_sqft}, Rate: {item.rate}"
            )
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"status": "success", "message": msg})
            messages.success(request, msg)
            return redirect("booking_list")

        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"status": "error", "message": format_form_errors(form)})
        messages.error(request, format_form_errors(form))
    else:
        form = BookingPlotSwapForm(booking)

    return render(
        request,
        "bookings/booking_kgp_swap.html",
        {
            "booking": booking,
            "form": form,
            "current_item": current_item,
            "swap_targets": swap_targets,
            "page_title": "Swap Plot/Flat (Post-KGP)",
        },
    )


def _recalculate_booking_balance(booking: BookingMaster) -> None:
    balance, _ = BalanceMaster.objects.get_or_create(b_id=booking)
    balance.recalculate()
    balance.save()


def _swap_booking_plot_items(source_item: BookingItem, target_item: BookingItem) -> None:
    """Swap only plot/flat numbers — area, rate, and amounts stay with each booking."""
    source_item.plot_number, target_item.plot_number = (
        target_item.plot_number,
        source_item.plot_number,
    )
    source_item.save(update_fields=["plot_number"])
    target_item.save(update_fields=["plot_number"])


@login_required
@require_POST
@transaction.atomic
def booking_delete(request, b_id: int):
    booking = get_object_or_404(BookingMaster, pk=b_id)
    booking_no = booking.booking_no
    booking.delete()
    log_activity(request.user, ActivityLog.Action.DELETE, "Booking",
                 b_id, booking_no, "Booking deleted.")
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({"status": "success", "message": "Booking deleted."})
    messages.success(request, "Booking deleted.")
    return redirect("booking_list")


@login_required
@require_POST
@transaction.atomic
def booking_cancel(request, b_id: int):
    booking = get_object_or_404(BookingMaster, pk=b_id)
    if request.method == "POST":
        reason = request.POST.get("reason", "Cancelled by user")
        
        # Soft cancel
        booking.status = "CANCELLED"
        booking.save()
        
        # Create CancelledPlot record
        from .models import CancelledPlot
        try:
            paid_amount = booking.balance.paid_amount
        except:
            paid_amount = 0
            
        try:
            plot_number = booking.balance.display_plot_number
        except:
            plot_number = ""
            
        CancelledPlot.objects.get_or_create(
            b_id=booking,
            defaults={
                "reason": reason,
                "plot_number": plot_number,
                "paid_amount": paid_amount,
                "created_by": request.user
            }
        )
        
        log_activity(request.user, ActivityLog.Action.CANCEL, "Booking",
                     booking.b_id, booking.booking_no, f"Cancelled. Reason: {reason}")
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": "Booking cancelled successfully."})
        messages.success(request, "Booking cancelled successfully.")
        return redirect("booking_list")
    from django.http import HttpResponseForbidden
    return HttpResponseForbidden()


@login_required
def booking_download(request, b_id: int):
    booking = (
        BookingMaster.objects.select_related("p_id", "u_id")
        .prefetch_related("items")
        .get(pk=b_id)
    )

    html = render_to_string(
        "bookings/booking_download.html",
        {"booking": booking},
        request=request,
    )
    response = HttpResponse(html, content_type="text/html")
    response["Content-Disposition"] = (
        f'attachment; filename="booking_{booking.b_id}.html"'
    )
    return response


def _booking_to_customer_payload(booking):
    return {
        "full_name": booking.full_name or "",
        "email": booking.email or "",
        "date_of_birth": booking.date_of_birth.strftime("%Y-%m-%d") if booking.date_of_birth else "",
        "occupation": booking.occupation or "",
        "present_address": booking.present_address or "",
        "permanent_address": booking.permanent_address or "",
        "aadhar_number": booking.aadhar_number or "",
        "pin_code": booking.pin_code or "",
        "nominee": booking.nominee or "",
        "relationship": booking.relationship or "",
    }


def _customer_profile_payload(customer):
    return {
        "full_name": customer.full_name or "",
        "email": customer.email or "",
        "date_of_birth": customer.date_of_birth.strftime("%Y-%m-%d") if customer.date_of_birth else "",
        "occupation": customer.occupation or "",
        "present_address": customer.present_address or "",
        "permanent_address": customer.permanent_address or "",
        "aadhar_number": customer.aadhar_number or "",
        "pin_code": customer.pin_code or "",
        "nominee": customer.nominee or "",
        "relationship": customer.relationship or "",
    }


def lookup_customer_by_phone(phone):
    """Merge customer user profile and latest booking snapshot for auto-fill."""
    from accounts.models import Users, Customer

    data = {}
    user = Users.objects.filter(phone=phone).select_related("customer").first()
    if user:
        data["full_name"] = user.full_name or ""
        data["email"] = user.email or ""
        try:
            profile = user.customer
            for key, value in _customer_profile_payload(profile).items():
                if value:
                    data[key] = value
        except Customer.DoesNotExist:
            pass

    latest_booking = BookingMaster.objects.filter(phone=phone).order_by("-b_id").first()
    if latest_booking:
        for key, value in _booking_to_customer_payload(latest_booking).items():
            if value:
                data[key] = value

    return data if data else None


def sync_customer_from_booking(booking):
    """Create or update registered customer profile from booking customer fields."""
    from accounts.models import Users, Customer
    from saas.tenant import assign_user_to_organization

    phone = (booking.phone or "").strip()
    if not phone:
        return None

    org = booking.organization
    if not org and booking.p_id_id:
        org = booking.p_id.organization

    user = None
    if org:
        user = Users.objects.filter(phone=phone, organization=org).first()
    if not user:
        user = Users.objects.filter(phone=phone).first()
    if not user:
        email = (booking.email or "").strip().lower()
        if not email:
            email = f"{phone}@booking.local"
        suffix = 1
        while Users.objects.filter(email=email).exists():
            email = f"{phone}.{suffix}@booking.local"
            suffix += 1
        user = Users(
            username=email,
            email=email,
            full_name=booking.full_name or f"Customer {phone[-4:]}",
            phone=phone,
            role="customer",
            organization=org,
        )
        user.set_unusable_password()
        user.save()
        if org:
            assign_user_to_organization(user, org)

    if booking.full_name:
        user.full_name = booking.full_name
    if booking.email:
        user.email = booking.email
    user.save(update_fields=["full_name", "email"])

    customer, _ = Customer.objects.get_or_create(
        u_id=user,
        defaults={"aadhar_number": booking.aadhar_number or ""},
    )
    customer.full_name = user.full_name
    customer.phone = phone
    customer.email = user.email
    customer.aadhar_number = booking.aadhar_number or customer.aadhar_number
    customer.date_of_birth = booking.date_of_birth
    customer.occupation = booking.occupation or ""
    customer.present_address = booking.present_address or ""
    customer.permanent_address = booking.permanent_address or ""
    customer.pin_code = booking.pin_code or ""
    customer.nominee = booking.nominee or ""
    customer.relationship = booking.relationship or ""
    customer.save()

    return user


@require_GET
@login_required
def customer_by_phone(request):
    phone = (request.GET.get("phone") or "").strip()
    if not phone.isdigit() or len(phone) < 10:
        return JsonResponse({"found": False, "error": "Invalid phone"}, status=400)

    from accounts.models import Users

    data = lookup_customer_by_phone(phone)
    if data:
        return JsonResponse({
            "found": True,
            "registered": Users.objects.filter(phone=phone).exists(),
            "data": data,
        })
    return JsonResponse({"found": False, "registered": False})


@require_GET
@login_required
def agent_details(request):
    from saas.tenant import tenant_agents
    from .models import AgentMaster
    u_id = request.GET.get("u_id")
    role = request.GET.get("role")
    if not u_id or not role:
        return JsonResponse({"error": "Missing parameters"}, status=400)
    
    agent = tenant_agents(request).filter(u_id=u_id, role=role).first()
    if agent:
        return JsonResponse({
            "percentage": float(agent.commission_percentage),
            "tds_amount": float(agent.tds_amount),
            "security_amount": float(agent.security_amount)
        })
    return JsonResponse({
        "percentage": 0.00,
        "tds_amount": 0.00,
        "security_amount": 0.00
    })


def _accounts_debit_totals(agent):
    """Sum commission and security debit payments for an accounts profile."""
    from .models import AccountsDebitPayment

    commission = Decimal("0.00")
    security = Decimal("0.00")
    if not agent:
        return commission, security
    for p in agent.debit_payments.all():
        if p.debit_type == AccountsDebitPayment.DebitType.COMMISSION:
            commission += p.amount
        elif p.debit_type == AccountsDebitPayment.DebitType.SECURITY:
            security += p.amount
    return commission, security


def _booking_commission(paid_amount, percentage):
    pct = percentage or Decimal("0.00")
    paid = paid_amount or Decimal("0.00")
    if pct <= 0 or paid <= 0:
        return Decimal("0.00")
    return (paid * pct) / 100


def _agent_role_profile(user_id, role, cache, request=None):
    if not user_id:
        return None
    key = (user_id, role)
    if key not in cache:
        if request is not None:
            from saas.tenant import tenant_agents
            cache[key] = tenant_agents(request).filter(u_id_id=user_id, role=role).first()
        else:
            cache[key] = AgentMaster.objects.filter(u_id_id=user_id, role=role).first()
    return cache[key]


def _team_member_summary(bookings, profile_cache, request=None):
    """Per team member: commission earned, deductions, account debits, and balance."""
    from .models import AccountsDebitPayment
    from saas.tenant import tenant_agents

    members = {}

    def _ensure_member(user_id, role, user):
        key = (user_id, role)
        if key not in members:
            profile = _agent_role_profile(user_id, role, profile_cache, request)
            members[key] = {
                "user": user,
                "role": role,
                "role_display": dict(AgentMaster.Role.choices).get(role, role),
                "tds_pct": profile.tds_amount if profile else Decimal("0.00"),
                "security_pct": profile.security_amount if profile else Decimal("0.00"),
                "commission_earned": Decimal("0.00"),
                "tds": Decimal("0.00"),
                "security": Decimal("0.00"),
            }
        return members[key]

    for booking in bookings:
        paid = booking.balance.paid_amount if booking.balance else Decimal("0.00")

        if booking.manager_u_id_id:
            entry = _ensure_member(
                booking.manager_u_id_id, "manager", booking.manager_u_id
            )
            comm = _booking_commission(paid, booking.manager_percentage)
            entry["commission_earned"] += comm
            entry["tds"] += (
                (comm * entry["tds_pct"]) / 100 if entry["tds_pct"] else Decimal("0.00")
            )
            entry["security"] += (
                (comm * entry["security_pct"]) / 100
                if entry["security_pct"]
                else Decimal("0.00")
            )

        if booking.executive_u_id_id:
            entry = _ensure_member(
                booking.executive_u_id_id, "executive", booking.executive_u_id
            )
            comm = _booking_commission(paid, booking.executive_percentage)
            entry["commission_earned"] += comm
            entry["tds"] += (
                (comm * entry["tds_pct"]) / 100 if entry["tds_pct"] else Decimal("0.00")
            )
            entry["security"] += (
                (comm * entry["security_pct"]) / 100
                if entry["security_pct"]
                else Decimal("0.00")
            )

        if booking.telecaller_u_id_id:
            entry = _ensure_member(
                booking.telecaller_u_id_id, "telecaller", booking.telecaller_u_id
            )
            comm = _booking_commission(paid, booking.telecaller_percentage)
            entry["commission_earned"] += comm
            entry["tds"] += (
                (comm * entry["tds_pct"]) / 100 if entry["tds_pct"] else Decimal("0.00")
            )
            entry["security"] += (
                (comm * entry["security_pct"]) / 100
                if entry["security_pct"]
                else Decimal("0.00")
            )

    breakdown = []
    total_commission_debit = Decimal("0.00")
    total_security_debit = Decimal("0.00")

    for (user_id, role), data in members.items():
        accounts_qs = tenant_agents(request) if request is not None else AgentMaster.objects
        accounts_entry = (
            accounts_qs.filter(
                u_id_id=user_id, role=AgentMaster.Role.ACCOUNTS
            )
            .prefetch_related("debit_payments")
            .first()
        )
        comm_debit, sec_debit = _accounts_debit_totals(accounts_entry)
        commission_payments = []
        security_payments = []
        if accounts_entry:
            for p in accounts_entry.debit_payments.all():
                if p.debit_type == AccountsDebitPayment.DebitType.COMMISSION:
                    commission_payments.append(p)
                elif p.debit_type == AccountsDebitPayment.DebitType.SECURITY:
                    security_payments.append(p)

        net_commission = data["commission_earned"] - data["tds"] - data["security"]
        balance = net_commission - comm_debit - sec_debit

        breakdown.append(
            {
                **data,
                "commission_debit": comm_debit,
                "security_debit": sec_debit,
                "net_commission": net_commission,
                "balance": balance,
                "balance_type": "CR" if balance >= 0 else "DR",
                "commission_payments": commission_payments,
                "security_payments": security_payments,
            }
        )
        total_commission_debit += comm_debit
        total_security_debit += sec_debit

    breakdown.sort(key=lambda x: (x["role"], x["user"].full_name if x["user"] else ""))
    return breakdown, total_commission_debit, total_security_debit


@login_required
def agent_list(request, role):
    from saas.tenant import tenant_agents

    agents_qs = tenant_agents(request).filter(role=role).select_related("u_id")
    if role == "accounts":
        agents_qs = agents_qs.prefetch_related("debit_payments")
    agents = list(agents_qs)
    if role == "accounts":
        for a in agents:
            comm, sec = _accounts_debit_totals(a)
            a.commission_debit_total = comm
            a.security_debit_total = sec
            a.payment_count = a.debit_payments.count()
    role_display = dict(AgentMaster.Role.choices).get(role, role.capitalize())
    return render(request, "bookings/agent_list.html", {
        "agents": agents,
        "role": role,
        "role_display": role_display
    })


@login_required
def accounts_transactions(request, am_id):
    """View all debit payment transactions for an accounts profile."""
    from saas.tenant import tenant_agents
    from .models import AccountsDebitPayment

    agent = get_object_or_404(
        tenant_agents(request)
        .select_related("u_id")
        .prefetch_related("debit_payments"),
        pk=am_id,
        role=AgentMaster.Role.ACCOUNTS,
    )
    payments = list(agent.debit_payments.all().order_by("-payment_date", "-adp_id"))
    commission_total, security_total = _accounts_debit_totals(agent)
    grand_total = commission_total + security_total

    return render(
        request,
        "bookings/accounts_transactions.html",
        {
            "agent": agent,
            "payments": payments,
            "commission_total": commission_total,
            "security_total": security_total,
            "grand_total": grand_total,
            "payment_type_choices": AccountsDebitPayment.DebitType.choices,
        },
    )


@login_required
def accounts_payment_edit(request, adp_id):
    """Edit a single AccountsDebitPayment entry."""
    from saas.tenant import tenant_agents
    from .models import AccountsDebitPayment
    from .forms import AccountsDebitPaymentForm

    payment = get_object_or_404(
        AccountsDebitPayment.objects.filter(agent_master__in=tenant_agents(request)),
        pk=adp_id,
    )
    am_id = payment.agent_master_id

    if request.method == "POST":
        form = AccountsDebitPaymentForm(request.POST, instance=payment)
        if form.is_valid():
            form.save()
            messages.success(request, "Payment updated.")
            log_activity(request.user, ActivityLog.Action.EDIT, "Accounts Payment",
                         adp_id, str(payment), "Payment entry updated.")
        else:
            messages.error(request, "Could not update payment.")
    return redirect("accounts_transactions", am_id=am_id)


@login_required
def accounts_payment_delete(request, adp_id):
    """Delete a single AccountsDebitPayment entry."""
    from saas.tenant import tenant_agents
    from .models import AccountsDebitPayment

    payment = get_object_or_404(
        AccountsDebitPayment.objects.filter(agent_master__in=tenant_agents(request)),
        pk=adp_id,
    )
    am_id = payment.agent_master_id

    if request.method == "POST":
        repr_str = str(payment)
        payment.delete()
        messages.success(request, "Payment deleted.")
        log_activity(request.user, ActivityLog.Action.DELETE, "Accounts Payment",
                     adp_id, repr_str, "Payment entry deleted.")
    return redirect("accounts_transactions", am_id=am_id)


@login_required
def agent_add(request, role):
    role_display = dict(AgentMaster.Role.choices).get(role, role.capitalize())
    if request.method == "POST":
        form = AgentMasterForm(request.POST, role=role, request=request)
        if role == "accounts":
            u_id_obj = form.cleaned_data.get("u_id") if form.is_valid() else None
            agent_stub = None
            if u_id_obj:
                from saas.tenant import tenant_agents

                agent_stub, _ = tenant_agents(request).get_or_create(
                    u_id=u_id_obj, role=role, defaults={"remarks": ""}
                )
            payment_formset = AccountsDebitPaymentFormSet(
                request.POST, instance=agent_stub, prefix=ACCOUNTS_PAYMENT_FORMSET_PREFIX
            )
            if form.is_valid() and payment_formset.is_valid():
                from saas.tenant import tenant_agents

                agent, _ = tenant_agents(request).update_or_create(
                    u_id=form.cleaned_data["u_id"],
                    role=role,
                    defaults={
                        "effective_date": form.cleaned_data.get("effective_date"),
                    },
                )
                payment_formset.instance = agent
                payment_formset.save()
                msg = "Accounts saved with payment entries."
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"status": "success", "message": msg})
                messages.success(request, msg)
                return redirect("agent_list", role=role)
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                errors = {**form.errors, **payment_formset.errors}
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Invalid form data.",
                        "errors": errors,
                    }
                )
        elif form.is_valid():
            agent = form.save(commit=False)
            agent.role = role
            agent.save()
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse(
                    {"status": "success", "message": f"{role.capitalize()} saved successfully."}
                )
            messages.success(request, f"{role.capitalize()} saved successfully.")
            return redirect("agent_list", role=role)
        elif request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"status": "error", "message": "Invalid form data.", "errors": form.errors.as_json()}
            )
    else:
        form = AgentMasterForm(role=role, request=request)
        payment_formset = (
            AccountsDebitPaymentFormSet(prefix=ACCOUNTS_PAYMENT_FORMSET_PREFIX)
            if role == "accounts"
            else None
        )

    context = {
        "form": form,
        "title": f"Add {role_display}",
        "role": role,
    }
    if role == "accounts":
        context["payment_formset"] = payment_formset
    return render(request, "bookings/agent_form.html", context)


@login_required
def agent_edit(request, am_id):
    from saas.tenant import tenant_agents

    agent = get_object_or_404(tenant_agents(request), pk=am_id)
    role = agent.role
    role_display = dict(AgentMaster.Role.choices).get(role, role.capitalize())
    if request.method == "POST":
        form = AgentMasterForm(request.POST, instance=agent, role=role, request=request)
        if role == "accounts":
            payment_formset = AccountsDebitPaymentFormSet(
                request.POST, instance=agent, prefix=ACCOUNTS_PAYMENT_FORMSET_PREFIX
            )
            if form.is_valid() and payment_formset.is_valid():
                form.save()
                payment_formset.save()
                msg = "Accounts updated. New payments were added to the list."
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"status": "success", "message": msg})
                messages.success(request, msg)
                return redirect("agent_list", role=role)
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse(
                    {"status": "error", "message": "Invalid form data.", "errors": form.errors}
                )
        elif form.is_valid():
            form.save()
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse(
                    {"status": "success", "message": f"{role.capitalize()} updated successfully."}
                )
            messages.success(request, f"{role.capitalize()} updated successfully.")
            return redirect("agent_list", role=role)
        elif request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"status": "error", "message": "Invalid form data.", "errors": form.errors.as_json()}
            )
    else:
        form = AgentMasterForm(instance=agent, role=role, request=request)
        payment_formset = (
            AccountsDebitPaymentFormSet(instance=agent, prefix=ACCOUNTS_PAYMENT_FORMSET_PREFIX)
            if role == "accounts"
            else None
        )

    context = {
        "form": form,
        "title": f"Edit {role_display}",
        "role": role,
    }
    if role == "accounts":
        context["payment_formset"] = payment_formset
    return render(request, "bookings/agent_form.html", context)


@login_required
@require_POST
def agent_delete(request, am_id):
    from saas.tenant import tenant_agents

    agent = get_object_or_404(tenant_agents(request), pk=am_id)
    role = agent.role
    agent.delete()
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({"status": "success", "message": f"{role.capitalize()} deleted successfully."})
    
    messages.success(request, f"{role.capitalize()} deleted successfully.")
    return redirect("agent_list", role=role)
@login_required
def project_list(request):
    from saas.tenant import scope_queryset_to_org
    projects = scope_queryset_to_org(Project.objects.all(), request).order_by("-p_id")
    return render(request, "bookings/project_list.html", {"projects": projects})


@login_required
def project_add(request):
    from saas.tenant import get_request_organization, organization_within_limits

    org = get_request_organization(request)
    if org and not organization_within_limits(org, "projects"):
        messages.error(request, "Project limit reached for your plan. Please upgrade to add more projects.")
        return redirect("project_list")

    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.organization = org
            project.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "success", "message": "Project added successfully."})
            messages.success(request, "Project added successfully.")
            return redirect("project_list")
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Invalid form data.", "errors": form.errors.as_json()})
    else:
        form = ProjectForm()
    return render(request, "bookings/project_form.html", {"form": form, "title": "Add Project"})


@login_required
def project_edit(request, p_id):
    from saas.tenant import scope_queryset_to_org
    project = get_object_or_404(scope_queryset_to_org(Project.objects.all(), request), pk=p_id)
    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "success", "message": "Project updated successfully."})
            messages.success(request, "Project updated successfully.")
            return redirect("project_list")
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Invalid form data.", "errors": form.errors.as_json()})
    else:
        form = ProjectForm(instance=project)
    return render(request, "bookings/project_form.html", {"form": form, "title": "Edit Project"})


@login_required
@require_POST
def project_delete(request, p_id):
    from saas.tenant import scope_queryset_to_org

    project = get_object_or_404(scope_queryset_to_org(Project.objects.all(), request), pk=p_id)
    project.delete()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({"status": "success", "message": "Project deleted successfully."})
    messages.success(request, "Project deleted successfully.")
    return redirect("project_list")


@login_required
def booking_agent_settings(request):
    if not request.user.has_role("admin"):
        return HttpResponseForbidden("Only Admins can change booking agent settings.")

    from saas.tenant import get_booking_agent_settings_for_request

    settings_obj = get_booking_agent_settings_for_request(request)
    if request.method == "POST":
        form = BookingAgentSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            obj = form.save(commit=False)
            from saas.tenant import get_request_organization
            org = get_request_organization(request)
            if org and not obj.organization_id:
                obj.organization = org
            obj.save()
            messages.success(request, "Store settings saved.")
            return redirect("booking_agent_settings")
        messages.error(request, "Please correct the errors below.")
    else:
        form = BookingAgentSettingsForm(instance=settings_obj)

    return render(
        request,
        "bookings/booking_agent_settings.html",
        {"form": form, "settings_obj": settings_obj},
    )


@login_required
def check_plot_availability(request):
    project_id = request.GET.get("project_id")
    plot_numbers = request.GET.get("plot_numbers", "")
    exclude_booking_id = request.GET.get("exclude_booking_id")
    
    if not project_id or not plot_numbers:
        return JsonResponse({"available": True})

    from saas.tenant import scope_queryset_to_org

    project = get_object_or_404(scope_queryset_to_org(Project.objects.all(), request), pk=project_id)
    max_plots = project.num_plots
    
    plots_to_check = [p.strip() for p in plot_numbers.split(",") if p.strip()]
    invalid_range = []
    already_booked = []

    # Check for valid range first
    if max_plots > 0:
        for plot in plots_to_check:
            if plot.isdigit() and int(plot) > max_plots:
                invalid_range.append(plot)
    
    if invalid_range:
        return JsonResponse({
            "available": False, 
            "invalid_range": invalid_range,
            "message": f"Invalid Plot(s): {', '.join(invalid_range)}. Project only has {max_plots} plots."
        })
    
    # Get all booked plots for this project, EXCLUDING the current booking
    already_booked = []
    from django.db.models import Q
    
    for plot in plots_to_check:
        query = BookingItem.objects.filter(p_id_id=project_id).filter(
            Q(plot_number=plot) | 
            Q(plot_number__startswith=plot+",") | 
            Q(plot_number__contains=","+plot+",") | 
            Q(plot_number__endswith=","+plot)
        ).exclude(
            b_id__status="CANCELLED",
            b_id__cancelled_details__closure_status="CLOSED",
            b_id__cancelled_details__released_for_rebooking=True
        )
        
        if exclude_booking_id and str(exclude_booking_id).isdigit():
            query = query.exclude(b_id_id=exclude_booking_id)
            
        if query.exists():
            already_booked.append(plot)
            
    if already_booked:
        return JsonResponse({
            "available": False, 
            "booked_plots": already_booked,
            "message": f"Already booked: {', '.join(already_booked)}"
        })
    
    return JsonResponse({"available": True})


@login_required
def master_plots(request):
    from saas.tenant import tenant_bookings, tenant_projects

    projects = tenant_projects(request).order_by("name")
    project_data = []
    
    for project in projects:
        # Get booking items for this project within the current organization
        items = (
            BookingItem.objects.filter(p_id=project, b_id__in=tenant_bookings(request))
            .select_related("b_id", "b_id__cancelled_details")
        )
        
        # Map plot_number -> status
        plot_status_map = {}
        for item in items:
            if not item.plot_number:
                continue
            for p in item.plot_number.split(","):
                cleaned = p.strip()
                if not cleaned:
                    continue
                
                b = item.b_id
                if b.status == "CANCELLED":
                    if hasattr(b, 'cancelled_details'):
                        cp = b.cancelled_details
                        if cp.refund_status == "COMPLETED" and cp.closure_status == "CLOSED" and cp.released_for_rebooking:
                            if cleaned not in plot_status_map:
                                plot_status_map[cleaned] = "available"
                        else:
                            if plot_status_map.get(cleaned) != "booked":
                                plot_status_map[cleaned] = "awaiting_closure"
                    else:
                        if plot_status_map.get(cleaned) != "booked":
                            plot_status_map[cleaned] = "awaiting_closure"
                else:
                    plot_status_map[cleaned] = "booked"
        
        plots = []
        booked_count = 0
        awaiting_count = 0
        available_count = 0
        
        if project.num_plots > 0:
            for i in range(1, project.num_plots + 1):
                plot_num = str(i)
                status = plot_status_map.get(plot_num, "available")
                if status == "booked":
                    booked_count += 1
                elif status == "awaiting_closure":
                    awaiting_count += 1
                else:
                    available_count += 1
                
                plots.append({
                    "number": plot_num,
                    "status": status
                })
        
        project_data.append({
            "project": project,
            "plots": plots,
            "booked_count": booked_count,
            "available_count": available_count,
            "awaiting_count": awaiting_count
        })
        
    return render(request, "bookings/master_plots.html", {
        "project_data": project_data,
        "page_title": "Master Plot Design"
    })


@login_required
def receipt_list(request):
    from saas.tenant import tenant_payments, tenant_receipts

    receipts = tenant_receipts(request).exclude(b_id__status="CANCELLED").select_related("b_id__p_id").order_by("-rm_id")
    if request.user.has_role("manager") and not request.user.has_role("admin"):
        receipts = receipts.filter(b_id__created_by=request.user)
    elif request.user.has_role("customer"):
        receipts = receipts.filter(b_id__u_id=request.user)
        pending_payments = tenant_payments(request).filter(b_id__u_id=request.user, status=Payment.Status.PENDING).select_related('b_id__p_id').order_by("-created_at")
        return render(request, "bookings/customer_payment_history.html", {
            "receipts": receipts,
            "pending_payments": pending_payments
        })
    return render(request, "bookings/receipt_list.html", {"receipts": receipts})


@login_required
@transaction.atomic
def receipt_add(request):
    if not request.user.has_any_role("admin", "accounts"):
        messages.error(request, "Managers must use Payment Requests for approval.")
        return redirect("payment_add")
    
    if request.method == "POST":
        form = ReceiptMasterForm(request.POST)
        if form.is_valid():
            receipt = form.save(commit=False)
            if receipt.b_id.status == "CANCELLED":
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"status": "error", "message": "Cannot add receipt for a cancelled booking."})
                messages.error(request, "Cannot add receipt for a cancelled booking.")
                return redirect("receipt_list")
            
            receipt.save()
            
            # Update BalanceMaster using robust recalculation logic
            balance, _ = BalanceMaster.objects.get_or_create(b_id=receipt.b_id)
            balance.recalculate()
            balance.save()
            
            # Sync next_payment_date to BookingMaster
            if receipt.next_payment_date:
                booking = receipt.b_id
                booking.next_payment_date = receipt.next_payment_date
                booking.save()
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "success", "message": f"Receipt created (Receipt No: {receipt.receipt_no})."})
            messages.success(request, f"Receipt created (Receipt No: {receipt.receipt_no}).")
            return redirect("receipt_list")
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": format_form_errors(form)})
            messages.error(request, "Please correct the errors and try again.")
    else:
        form = ReceiptMasterForm()
    
    return render(request, "bookings/receipt_form.html", {"form": form, "page_title": "Add Receipt"})


@login_required
def receipt_view(request, rm_id):
    from .models import get_booking_agent_settings
    from .share_utils import build_receipt_share

    receipt = get_object_or_404(
        ReceiptMaster.objects.select_related("b_id", "b_id__u_id"), pk=rm_id
    )
    company_name = get_booking_agent_settings().company_name or "LANDLINK REAL ESTATE"
    share = build_receipt_share(receipt, company_name)
    return render(
        request,
        "bookings/receipt_view.html",
        {
            "receipt": receipt,
            "share": share,
            "send_email_url": reverse("receipt_share_email", kwargs={"rm_id": rm_id}),
        },
    )


@login_required
@transaction.atomic
def receipt_edit(request, rm_id):
    receipt = get_object_or_404(ReceiptMaster, pk=rm_id)
    if request.method == "POST":
        # Capture old values before form saves
        old_pay_amount = receipt.pay_amount
        old_total_amount = receipt.total_amount
        old_payment_method = receipt.payment_method

        form = ReceiptMasterForm(request.POST, instance=receipt)
        if form.is_valid():
            receipt = form.save(commit=False)
            # Rule 3: Ensure b_id is preserved correctly
            receipt.b_id = get_object_or_404(BookingMaster, pk=receipt.b_id_id)
            receipt.save()
            # Recalculate balance
            balance, _ = BalanceMaster.objects.get_or_create(b_id=receipt.b_id)
            balance.recalculate()
            balance.save()
            
            # Sync next_payment_date to BookingMaster
            if receipt.next_payment_date:
                booking = receipt.b_id
                booking.next_payment_date = receipt.next_payment_date
                booking.save()

            amount_change = f"{old_pay_amount} -> {receipt.pay_amount}" if old_pay_amount != receipt.pay_amount else str(receipt.pay_amount)
            total_change = f"{old_total_amount} -> {receipt.total_amount}" if old_total_amount != receipt.total_amount else str(receipt.total_amount)
            method_change = f"{old_payment_method} -> {receipt.payment_method}" if old_payment_method != receipt.payment_method else receipt.payment_method
            changes_str = (
                f"Customer: {receipt.customer_name} | Amount Paid: {amount_change} | "
                f"Total: {total_change} | Balance: {receipt.balance_amount} | "
                f"Method: {method_change} | Date: {receipt.receipt_date}"
            )
            log_activity(request.user, ActivityLog.Action.EDIT, "Receipt",
                         receipt.rm_id, receipt.receipt_no, changes_str)

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "success", "message": "Receipt updated successfully."})
            messages.success(request, "Receipt updated successfully.")
            return redirect("receipt_list")
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": format_form_errors(form)})
    else:
        form = ReceiptMasterForm(instance=receipt)
    
    return render(request, "bookings/receipt_form.html", {
        "form": form, 
        "page_title": "Edit Receipt",
        "is_edit": True
    })


@login_required
@require_POST
@transaction.atomic
def receipt_delete(request, rm_id):
    receipt = get_object_or_404(ReceiptMaster, pk=rm_id)
    booking = receipt.b_id
    receipt_no = receipt.receipt_no
    receipt.delete()
    
    # Recalculate balance after deletion
    balance, _ = BalanceMaster.objects.get_or_create(b_id=booking)
    balance.recalculate()
    balance.save()
    log_activity(request.user, ActivityLog.Action.DELETE, "Receipt",
                 rm_id, receipt_no, "Receipt deleted.")
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({"status": "success", "message": "Receipt deleted successfully."})
    messages.success(request, "Receipt deleted successfully.")
    return redirect("receipt_list")


@require_GET
@login_required
def booking_details_api(request):
    b_id = request.GET.get("b_id")
    if not b_id:
        return JsonResponse({"error": "Missing b_id"}, status=400)
    
    from saas.tenant import tenant_bookings

    booking = get_object_or_404(tenant_bookings(request), pk=b_id)
    balance, _ = BalanceMaster.objects.get_or_create(b_id=booking)
    
    # Get plot numbers from items
    plots = ", ".join([it.plot_number for it in booking.items.all() if it.plot_number])
    
    return JsonResponse({
        "customer_name": booking.customer_full_name,
        "phone": booking.customer_phone,
        "plot_number": plots,
        "total_amount": float(balance.total_amount),
        "balance_amount": float(balance.balance_amount),
    })


@require_GET
@login_required
def bookings_by_phone(request):
    from saas.tenant import tenant_bookings

    phone = (request.GET.get("phone") or "").strip()
    if not phone:
        return JsonResponse({"bookings": []})
    
    # Filter bookings by the linked customer's current phone number
    bookings = tenant_bookings(request).filter(
        u_id__phone=phone
    ).exclude(status='CANCELLED').distinct().order_by("-b_id")
    
    data = []
    for b in bookings:
        data.append({
            "id": b.b_id,
            "no": b.booking_no,
            "name": b.customer_full_name
        })
        
    return JsonResponse({"bookings": data})


@login_required
def ledger_list(request):
    from saas.tenant import tenant_bookings

    bookings = tenant_bookings(request).exclude(status="CANCELLED").select_related("u_id", "p_id").prefetch_related("items", "receipts").order_by("-b_id")
    if request.user.has_role("manager"):
        bookings = bookings.filter(created_by=request.user)
    elif request.user.has_role("customer"):
        bookings = bookings.filter(u_id=request.user)
        
        # Calculate ledgers
        ledgers = []
        for b in bookings:
            plot_no = ", ".join(filter(None, [it.plot_number for it in b.items.all()]))
            initial_paid = sum((it.booking_amount for it in b.items.all()), 0)
            total_val = b.balance.total_amount if hasattr(b, 'balance') and b.balance else sum((it.area_sqft * it.rate for it in b.items.all()), 0)
            
            transactions = []
            if initial_paid > 0:
                transactions.append({
                    'date': b.booking_date,
                    'mode': b.get_payment_method_display(),
                    'received': initial_paid,
                })
                
            b_receipts = b.receipts.all().order_by('receipt_date', 'created_at')
            for r in b_receipts:
                transactions.append({
                    'date': r.receipt_date,
                    'mode': r.get_payment_method_display(),
                    'received': r.pay_amount,
                })
                
            booking_ledger = []
            current_balance = total_val
            
            if not transactions:
                booking_ledger.append({
                    'date': b.booking_date,
                    'plot': plot_no,
                    'mode': '-',
                    'total': total_val,
                    'received': 0.0,
                    'balance': current_balance
                })
            else:
                for i, t in enumerate(transactions):
                    opening_balance = current_balance
                    current_balance -= t['received']
                    booking_ledger.append({
                        'date': t['date'],
                        'plot': plot_no,
                        'mode': t['mode'],
                        'total': opening_balance,
                        'received': t['received'],
                        'balance': current_balance
                    })
                
            ledgers.append({
                'booking': b,
                'transactions': booking_ledger,
                'final_balance': current_balance
            })
            
        return render(request, "bookings/customer_ledger.html", {"bookings": bookings, "ledgers": ledgers})
    return render(request, "bookings/ledger_list.html", {"bookings": bookings})


@login_required
def ledger_data_api(request):
    from saas.tenant import tenant_bookings

    b_id = request.GET.get("b_id")
    if not b_id:
        return JsonResponse({"error": "Booking ID required"}, status=400)
    
    booking = get_object_or_404(
        tenant_bookings(request).select_related("p_id", "balance").prefetch_related("items__p_id"),
        pk=b_id,
    )
    items = list(booking.items.all())
    receipts = booking.receipts.all().order_by("receipt_date", "rm_id")

    project_name = booking.p_id.name if booking.p_id else ""
    if not project_name and items:
        for it in items:
            if it.p_id_id:
                project_name = it.p_id.name
                break

    plot_parts = []
    for it in items:
        if it.plot_number:
            for p in it.plot_number.split(","):
                p = p.strip()
                if p and p not in plot_parts:
                    plot_parts.append(p)
    plot_numbers = ", ".join(plot_parts)
    if not plot_numbers and hasattr(booking, "balance") and booking.balance.plot_number:
        plot_numbers = booking.balance.plot_number

    total_area = sum((it.area_sqft or Decimal("0") for it in items), Decimal("0"))
    booking_amount = sum((it.booking_amount or Decimal("0") for it in items), Decimal("0.00"))
    total_amount = sum(
        ((it.area_sqft or Decimal("0")) * (it.rate or Decimal("0")) for it in items),
        Decimal("0.00"),
    )
    rate = (total_amount / total_area) if total_area > 0 else Decimal("0")
    
    # Receipt data
    receipt_data = []
    
    # Add initial booking amount as first entry
    if booking_amount > 0:
        receipt_data.append({
            "date": booking.booking_date.strftime("%d-%m-%Y") if booking.booking_date else "N/A",
            "bill_no": booking.booking_no,
            "receipt_no": "INITIAL PAYMENT",
            "amount": float(booking_amount),
            "mode": booking.get_payment_method_display() or "N/A"
        })
    
    total_received = booking_amount
    for r in receipts:
        receipt_data.append({
            "date": r.receipt_date.strftime("%d-%m-%Y"),
            "bill_no": booking.booking_no,
            "receipt_no": r.receipt_no,
            "amount": float(r.pay_amount),
            "mode": r.get_payment_method_display()
        })
        total_received += r.pay_amount
    
    def _display(val, fallback="—"):
        text = (str(val).strip() if val is not None else "") or fallback
        return text

    return JsonResponse({
        "header": {
            "customer_name": booking.customer_full_name,
            "booking_no": booking.booking_no,
            "phone": booking.customer_phone or "—",
            "booking_date": booking.booking_date.strftime("%d-%m-%Y") if booking.booking_date else "—",
        },
        "summary": {
            "project": _display(project_name),
            "plot_no": _display(plot_numbers),
            "area": f"{total_area:,.2f}" if total_area else "—",
            "rate": f"{rate:,.2f}" if rate else "—",
            "booking_amount": f"{booking_amount:,.2f}",
            "total_amount": f"{total_amount:,.2f}",
        },
        "receipts": receipt_data,
        "totals": {
            "received": f"{total_received:,.2f}",
            "balance": f"{(total_amount - total_received):,.2f}"
        }
    })


@login_required
def ledger_print(request, b_id):
    from saas.tenant import tenant_bookings

    booking = get_object_or_404(
        tenant_bookings(request).select_related("p_id", "balance").prefetch_related("items__p_id"),
        pk=b_id,
    )
    items = list(booking.items.all())
    receipts = booking.receipts.all().order_by("receipt_date", "rm_id")

    project_name = booking.p_id.name if booking.p_id else ""
    if not project_name and items:
        for it in items:
            if it.p_id_id:
                project_name = it.p_id.name
                break
    plot_parts = []
    for it in items:
        if it.plot_number:
            for p in it.plot_number.split(","):
                p = p.strip()
                if p and p not in plot_parts:
                    plot_parts.append(p)
    plot_numbers = ", ".join(plot_parts)
    if not plot_numbers and hasattr(booking, "balance") and booking.balance.plot_number:
        plot_numbers = booking.balance.plot_number

    total_area = sum((it.area_sqft or Decimal("0") for it in items), Decimal("0"))
    total_amount = sum(
        ((it.area_sqft or Decimal("0")) * (it.rate or Decimal("0")) for it in items),
        Decimal("0.00"),
    )
    rate = (total_amount / total_area) if total_area > 0 else Decimal("0")
    booking_amount = sum((it.booking_amount or Decimal("0") for it in items), Decimal("0.00"))
    
    total_received = booking_amount + sum((r.pay_amount for r in receipts), Decimal("0.00"))
    balance = total_amount - total_received

    context = {
        "booking": booking,
        "project_name": project_name,
        "plot_numbers": plot_numbers,
        "total_area": total_area,
        "rate": rate,
        "booking_amount": booking_amount,
        "total_amount": total_amount,
        "receipts": receipts,
        "total_received": total_received,
        "balance": balance,
    }
    return render(request, "bookings/ledger_print.html", context)


@login_required
def follow_up_report(request):
    from datetime import date, timedelta
    from django.db.models import Max
    today = date.today()
    
    filter_type = request.GET.get('filter', 'today')
    payment_status = request.GET.get('status', 'PARTIAL')
    
    # Base queryset with priority annotations
    qs = base_report_queryset(user=request.user).filter(payment_status=payment_status)
    
    if payment_status == 'PARTIAL':
        # Apply strict categories (Today, 7, 15, 30) and prioritize Receipt follow-ups
        qs = apply_report_filters(qs, request, 'paid_percentage_annotated')
    
    return render(request, "bookings/follow_up_report.html", {
        "bookings": qs,
        "filter_type": filter_type,
        "payment_status": payment_status,
        "page_title": "Follow-Up Report"
    })


from django.views.decorators.http import require_GET

@require_GET
def get_agent_info(request):
    """
    API to fetch TDS, Security, and Commission for a specific agent role.
    """
    uid = request.GET.get("user_id")
    role = request.GET.get("role")
    
    # This will appear in your terminal/console
    print(f">>> API CALL: agent-info | User: {uid} | Role: {role}")
    
    if not uid or not role:
        return JsonResponse({"status": "error", "message": "Missing parameters"}, status=400)
    
    from saas.tenant import tenant_agents
    from .models import AgentMaster
    try:
        agent = tenant_agents(request).filter(u_id_id=uid, role=role).first()
        if agent:
            data = {
                "status": "success",
                "tds": float(agent.tds_amount),
                "security": float(agent.security_amount),
                "commission": float(agent.commission_percentage)
            }
        else:
            data = {
                "status": "success",
                "tds": 0.0,
                "security": 0.0,
                "commission": 0.0
            }
        return JsonResponse(data)
    except Exception as e:
        print(f">>> API ERROR: {str(e)}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def agent_withdrawal_data(request):
    """
    API for admin: fetch total commission breakdown and accounts deduction settings for a user.
    Returns manager/executive/telecaller commission amounts plus withdrawal commission % and security amount.
    """
    user_id = request.GET.get("user_id")
    if not user_id:
        return JsonResponse({"status": "error", "message": "Missing user_id"}, status=400)

    try:
        from saas.tenant import tenant_agents, tenant_bookings

        # Accounts deduction settings for this agent
        accounts_entry = (
            tenant_agents(request).filter(u_id_id=user_id, role="accounts")
            .prefetch_related("debit_payments")
            .first()
        )
        commission_debit, security_debit = _accounts_debit_totals(accounts_entry)
        commission_pct = float(commission_debit)
        security_amount = float(security_debit)

        role_data = {}
        total_commission = Decimal("0.00")

        for role_key, booking_filter, pct_field in [
            ("manager", {"manager_u_id_id": user_id}, "manager_percentage"),
            ("executive", {"executive_u_id_id": user_id}, "executive_percentage"),
            ("telecaller", {"telecaller_u_id_id": user_id}, "telecaller_percentage"),
        ]:
            qs = tenant_bookings(request).filter(**booking_filter).exclude(status="CANCELLED").select_related("balance")
            role_commission = Decimal("0.00")
            for b in qs:
                try:
                    paid = b.balance.paid_amount
                except Exception:
                    paid = Decimal("0.00")
                pct = getattr(b, pct_field, Decimal("0.00")) or Decimal("0.00")
                role_commission += (paid * pct) / Decimal("100.00")
            role_data[role_key] = float(role_commission)
            total_commission += role_commission

        total_commission_f = float(total_commission)
        net_amount = total_commission_f - commission_pct - security_amount
        if net_amount < 0:
            net_amount = 0.0

        return JsonResponse({
            "status": "success",
            "commission_pct": commission_pct,
            "security_amount": security_amount,
            "manager_commission": role_data["manager"],
            "executive_commission": role_data["executive"],
            "telecaller_commission": role_data["telecaller"],
            "total_commission": total_commission_f,
            "net_amount": round(net_amount, 2),
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


from django.db.models import Sum, Max, F, DecimalField, ExpressionWrapper, Case, When, Value, Q, FloatField
from django.db.models.functions import Coalesce
from datetime import date, timedelta

def base_report_queryset(user=None, organization=None):
    """Returns a base queryset with all necessary annotations for reports."""
    from .models import BookingMaster, ReceiptMaster
    from decimal import Decimal
    from django.db.models import Subquery, OuterRef, Q
    from saas.tenant import get_user_organization

    latest_receipt_date = ReceiptMaster.objects.filter(
        b_id=OuterRef('pk'),
        next_payment_date__isnull=False
    ).order_by('-created_at').values('next_payment_date')[:1]

    qs = BookingMaster.objects.select_related('p_id', 'u_id', 'balance').exclude(status="CANCELLED")

    org = organization
    if org is None and user:
        org = get_user_organization(user)
    if org:
        qs = qs.filter(Q(organization=org) | Q(p_id__organization=org)).distinct()
    elif user and not getattr(user, "is_superuser", False):
        qs = qs.none()

    if user and user.has_role("manager") and not user.has_role("admin"):
        qs = qs.filter(created_by=user)
        
    return qs.annotate(
        total_sum_amount=Coalesce(F('balance__total_amount'), Value(Decimal("0.00"), output_field=DecimalField())),
        paid_amount_annotated=Coalesce(F('balance__paid_amount'), Value(Decimal("0.00"), output_field=DecimalField())),
        balance_amount_annotated=Coalesce(F('balance__balance_amount'), Value(Decimal("0.00"), output_field=DecimalField())),
        
        # Priority Logic: Latest Receipt Follow-up Date -> fallback to Booking Master Date
        receipt_followup_date_annotated=Subquery(latest_receipt_date),
        final_followup_date=Coalesce(Subquery(latest_receipt_date), F('next_payment_date')),
        
        # Labeling the source
        followup_source=Case(
            When(receipt_followup_date_annotated__isnull=False, then=Value("RECEIPT")),
            default=Value("BOOKING")
        ),
        
        paid_percentage_annotated=Case(
            When(total_sum_amount__gt=0, then=ExpressionWrapper(F('paid_amount_annotated') * 100.0 / F('total_sum_amount'), output_field=FloatField())),
            default=Value(0.0)
        )
    )

def apply_report_filters(qs, request, percentage_field):
    payment_status = request.GET.get('status', 'PARTIAL')
    
    # Default filter is 'today' for follow-up report, 'all' for others
    default_filter = 'today' if percentage_field == 'paid_percentage_annotated' else 'today' 
    # Wait, the user wants follow-up to be today.
    
    filter_type = request.GET.get('filter')
    if not filter_type:
        # If it's the follow-up report (we detect by percentage_field or view)
        # Actually, let's just use the view's preference.
        filter_type = 'all' # Default fallback
        
    tab = request.GET.get('tab')
    from_pct = request.GET.get('from_pct')
    to_pct = request.GET.get('to_pct')
    
    if not tab and "percentage-follow-up" in request.path:
        tab = '0-30'
        
    from datetime import date, timedelta
    today = date.today()


    # Manual % Filter
    if from_pct:
        qs = qs.filter(**{f"{percentage_field}__gte": float(from_pct)})
    if to_pct:
        qs = qs.filter(**{f"{percentage_field}__lte": float(to_pct)})

    # Tab Filter (STRICT Rule Boundaries)
    if tab == '0-30':
        qs = qs.filter(**{f"{percentage_field}__gte": 0, f"{percentage_field}__lte": 30})
    elif tab == '30-50':
        qs = qs.filter(**{f"{percentage_field}__gt": 30, f"{percentage_field}__lte": 50})
    elif tab == '50-75':
        qs = qs.filter(**{f"{percentage_field}__gt": 50, f"{percentage_field}__lte": 75})
    elif tab == '75-99' or tab == '75-100':
        qs = qs.filter(**{f"{percentage_field}__gt": 75, f"{percentage_field}__lt": 100})
    elif tab == '100':
        qs = qs.filter(**{f"{percentage_field}__gte": 99.99})

    # STRICT RULE: Exclude all past dates (no overdue)
    qs = qs.filter(final_followup_date__gte=today)

    # Date Filters (Using Strict Priority followup_date)
    if filter_type == 'today':
        qs = qs.filter(final_followup_date=today)
    elif filter_type == '7':
        qs = qs.filter(final_followup_date__gt=today, final_followup_date__lte=today + timedelta(days=7))
    elif filter_type == '15':
        qs = qs.filter(final_followup_date__gt=today + timedelta(days=7), final_followup_date__lte=today + timedelta(days=15))
    elif filter_type == '30':
        qs = qs.filter(final_followup_date__gt=today + timedelta(days=15), final_followup_date__lte=today + timedelta(days=30))
    
    return qs

@login_required
def percentage_follow_up(request):
    from .models import Project
    tab = request.GET.get('tab', '0-30')
    
    # Show all payment statuses (PARTIAL and FULL) so the 100% tab works
    qs = base_report_queryset(user=request.user)
    qs = apply_report_filters(qs, request, 'paid_percentage_annotated')

    return render(request, "bookings/percentage_follow_up.html", {
        "bookings": qs,
        "projects": Project.objects.all(),
        "tab": tab,
        "page_title": "Percentage Follow-Up"
    })

@login_required
def advance_follow_up(request):
    from .models import Project
    project_id = request.GET.get('project')
    
    # Simple Query: Partial payments for selected project
    if project_id:
        qs = base_report_queryset(user=request.user).filter(p_id=project_id)
        qs = apply_report_filters(qs, request, 'paid_percentage_annotated')
        bookings = qs
    else:
        bookings = []

    return render(request, "bookings/advance_follow_up.html", {
        "bookings": bookings,
        "projects": Project.objects.all(),
        "page_title": "Advance Booking"
    })
@login_required
def payment_request(request):
    if request.method == "POST":
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            if payment.b_id.status == "CANCELLED":
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"status": "error", "message": "Cannot add payment request for a cancelled booking."})
                messages.error(request, "Cannot add payment request for a cancelled booking.")
                return redirect("payment_list")
            
            payment.created_by = request.user
            payment.status = Payment.Status.PENDING
            payment.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "success", "message": "Payment request submitted for approval."})
            messages.success(request, "Payment request submitted for approval.")
            return redirect("payment_list")
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": format_form_errors(form)})
            messages.error(request, "Please correct the errors.")
    else:
        form = PaymentForm()
    
    return render(request, "bookings/receipt_form.html", { # Reusing receipt_form.html for UI consistency
        "form": form, 
        "page_title": "Add Payment Request",
        "is_payment": True
    })

@login_required
def payment_list(request):
    from saas.tenant import tenant_payments

    payments = tenant_payments(request).order_by("-created_at")
    if request.user.has_role("manager") and not request.user.has_role("admin"):
        payments = payments.filter(created_by=request.user)
    elif request.user.has_role("customer"):
        payments = payments.filter(b_id__u_id=request.user)

    return render(request, "bookings/payment_list.html", {
        "payments": payments,
        "page_title": "Payment Requests"
    })

@login_required
@transaction.atomic
def payment_approve(request, p_id):
    if not request.user.has_any_role("accounts", "admin"):
        return JsonResponse({"status": "error", "message": "Unauthorized"}, status=403)
    
    payment = get_object_or_404(Payment, pk=p_id)
    if payment.status != Payment.Status.PENDING:
        return JsonResponse({"status": "error", "message": "Payment already processed."})
    
    payment.status = Payment.Status.APPROVED
    payment.save()
    
    # Create Receipt
    booking = payment.b_id
    if booking.status == "CANCELLED":
        return JsonResponse({"status": "error", "message": "Cannot approve payment for a cancelled booking."})

    balance, _ = BalanceMaster.objects.get_or_create(b_id=booking)
    balance.recalculate()
    
    receipt = ReceiptMaster.objects.create(
        receipt_date=payment.payment_date,
        b_id=booking,
        customer_name=booking.customer_full_name,
        phone=booking.customer_phone,
        plot_number=", ".join([it.plot_number for it in booking.items.all() if it.plot_number]),
        total_amount=balance.total_amount,
        pay_amount=payment.pay_amount,
        balance_amount=balance.balance_amount - payment.pay_amount,
        payment_method=payment.payment_method,
        payment_details=payment.payment_details,
        next_payment_date=payment.next_payment_date
    )
    
    balance.recalculate()
    balance.save()
    
    if payment.next_payment_date:
        booking.next_payment_date = payment.next_payment_date
        booking.save()
        
    return JsonResponse({"status": "success", "message": f"Payment approved and receipt {receipt.receipt_no} created."})



@login_required
def all_reports_dashboard(request):
    return render(request, "bookings/all_reports.html", {
        "page_title": "Booking & Agent Reports",
    })

@login_required
def customer_wise_report(request):
    from accounts.models import Users
    customers = Users.filter_by_role("customer").order_by("full_name")
    customer_id = request.GET.get('customer')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    bookings = []
    total_paid = 0
    total_balance = 0
    
    if customer_id:
        bookings = BookingMaster.objects.filter(u_id_id=customer_id).exclude(status='CANCELLED').select_related('p_id', 'balance')
        if from_date:
            bookings = bookings.filter(booking_date__gte=from_date)
        if to_date:
            bookings = bookings.filter(booking_date__lte=to_date)
            
        # Calculate summary
        for b in bookings:
            total_paid += b.balance.paid_amount
            total_balance += b.balance.balance_amount
            
    return render(request, "bookings/customer_wise_report.html", {
        "customers": customers,
        "bookings": bookings,
        "total_paid": total_paid,
        "total_balance": total_balance,
        "selected_customer": customer_id,
        "from_date": from_date,
        "to_date": to_date,
        "page_title": "Customer Wise Report"
    })

@login_required
def project_wise_report(request):
    projects = Project.objects.all().order_by('name')
    project_id = request.GET.get('project')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    bookings = []
    total_val = 0
    total_paid = 0
    
    if project_id:
        bookings = BookingMaster.objects.filter(p_id_id=project_id).exclude(status='CANCELLED').select_related('u_id', 'balance')
        if from_date:
            bookings = bookings.filter(booking_date__gte=from_date)
        if to_date:
            bookings = bookings.filter(booking_date__lte=to_date)
            
        # Calculate summary
        for b in bookings:
            total_val += b.balance.total_amount
            total_paid += b.balance.paid_amount
            
    return render(request, "bookings/project_wise_report.html", {
        "projects": projects,
        "bookings": bookings,
        "total_val": total_val,
        "total_paid": total_paid,
        "selected_project": project_id,
        "from_date": from_date,
        "to_date": to_date,
        "page_title": "Project Wise Report"
    })

@login_required
def all_project_report(request):
    from django.db.models import Count, Sum
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # Summary of all projects
    project_stats = Project.objects.annotate(
        total_bookings=Count('bookings'),
        total_val=Sum('bookings__balance__total_amount'),
        total_paid=Sum('bookings__balance__paid_amount')
    ).order_by('name')
    
    total_global_val = 0
    total_global_bookings = 0

    # If date filters are applied, we need to filter the related bookings
    for p in project_stats:
        qs = p.bookings.exclude(status='CANCELLED')
        if from_date:
            qs = qs.filter(booking_date__gte=from_date)
        if to_date:
            qs = qs.filter(booking_date__lte=to_date)
        
        p.total_bookings = qs.count()
        p.total_val = qs.aggregate(Sum('balance__total_amount'))['balance__total_amount__sum'] or 0
        p.total_paid = qs.aggregate(Sum('balance__paid_amount'))['balance__paid_amount__sum'] or 0
        
        # Add a calculated property for template
        if p.total_val and p.total_val > 0:
            p.collection_percentage = (p.total_paid / p.total_val) * 100
        else:
            p.collection_percentage = 0
            
        total_global_val += p.total_val
        total_global_bookings += p.total_bookings
            
    return render(request, "bookings/all_project_report.html", {
        "project_stats": project_stats,
        "total_global_val": total_global_val,
        "total_global_bookings": total_global_bookings,
        "from_date": from_date,
        "to_date": to_date,
        "page_title": "All Project Summary"
    })

@login_required
def my_payments(request):
    if not request.user.has_role("customer"):
        return HttpResponseForbidden("This page is for customers only.")
    
    from .models import BookingMaster, Payment, BalanceMaster
    from decimal import Decimal
    from collections import defaultdict
    
    bookings = BookingMaster.objects.filter(u_id=request.user).exclude(status='CANCELLED').select_related('p_id', 'balance').prefetch_related('items')
    
    # Calculate global balance
    total_amount = Decimal("0.00")
    total_paid = Decimal("0.00")
    total_balance = Decimal("0.00")
    
    # Group bookings by project for the template
    project_bookings = defaultdict(list)
    
    for b in bookings:
        try:
            total_amount += b.balance.total_amount
            total_paid += b.balance.paid_amount
            total_balance += b.balance.balance_amount
            
            project_bookings[b.p_id].append({
                "id": b.b_id,
                "no": b.booking_no,
                "plots": b.balance.display_plot_number
            })
        except Exception as e:
            print(f"Error processing booking {b.b_id}: {e}")
            pass

    if request.method == "POST":
        b_id = request.POST.get("b_id")
        pay_amount = request.POST.get("pay_amount")
        payment_method = request.POST.get("payment_method")
        payment_details = request.POST.get("payment_details", "")
        
        if not b_id or not pay_amount or not payment_method:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "All fields are required."})
            messages.error(request, "All fields are required.")
            return redirect("my_payments")
            
        booking = get_object_or_404(BookingMaster, pk=b_id, u_id=request.user)
        
        if booking.status == "CANCELLED":
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Cannot add payment for a cancelled booking."})
            messages.error(request, "Cannot add payment for a cancelled booking.")
            return redirect("my_payments")
        
        # Validation
        try:
            amt = Decimal(pay_amount)
            if amt <= 0:
                raise ValueError()
        except:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Invalid amount."})
            messages.error(request, "Invalid amount.")
            return redirect("my_payments")
            
        # Create Payment Request (PENDING)
        from datetime import date
        payment = Payment.objects.create(
            b_id=booking,
            pay_amount=amt,
            payment_date=date.today(),
            payment_method=payment_method,
            payment_details=payment_details,
            status=Payment.Status.PENDING,
            created_by=request.user
        )
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": "Payment submitted successfully and is pending approval."})
        messages.success(request, "Payment submitted successfully and is pending approval.")
        return redirect("my_payments")

    context = {
        "project_bookings": dict(project_bookings),
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_balance": total_balance,
        "page_title": "My Payments"
    }
    return render(request, "bookings/my_payments.html", context)


@login_required
def cancelled_plots_list(request):
    from .models import CancelledPlot
    from django.db.models import Sum
    from saas.tenant import tenant_cancelled_plots

    if request.user.has_role("customer"):
        qs = tenant_cancelled_plots(request).filter(b_id__u_id=request.user).select_related('b_id')
    elif request.user.has_role("manager") and not request.user.has_role("admin"):
        qs = tenant_cancelled_plots(request).filter(b_id__created_by=request.user).select_related('b_id')
    else:
        qs = tenant_cancelled_plots(request).select_related('b_id', 'b_id__p_id', 'created_by').order_by('-cancellation_date')
        
    from django.db.models import Count

    total_cancelled = qs.count()
    total_refunds_pending = qs.filter(refund_status='PENDING').aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
    total_refunds_paid = qs.aggregate(Sum('refund_amount_paid'))['refund_amount_paid__sum'] or 0
    
    # Analytics for Admin
    project_stats = []
    manager_stats = []
    if request.user.has_role("admin"):
        project_stats = qs.values('b_id__p_id__name').annotate(count=Count('cp_id'), amount=Sum('paid_amount')).order_by('-count')
        manager_stats = qs.values('b_id__created_by__full_name').annotate(count=Count('cp_id'), amount=Sum('paid_amount')).order_by('-count')
    
    context = {
        "cancelled_plots": qs,
        "page_title": "Cancelled Plots & Refunds",
        "total_cancelled": total_cancelled,
        "total_refunds_pending": total_refunds_pending,
        "total_refunds_paid": total_refunds_paid,
        "project_stats": project_stats,
        "manager_stats": manager_stats,
    }
    return render(request, "bookings/cancelled_plots.html", context)


@login_required
@require_POST
def update_refund_status(request, cp_id):
    if not request.user.has_any_role("admin", "accounts"):
        return JsonResponse({"status": "error", "message": "Unauthorized"}, status=403)
        
    from .models import CancelledPlot
    from decimal import Decimal
    
    plot = get_object_or_404(CancelledPlot, pk=cp_id)
    
    # IMPORTANT LOCK RULE
    if plot.refund_status == "COMPLETED" and plot.closure_status == "CLOSED":
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "This cancellation is fully completed and closed. Editing is locked."})
        messages.error(request, "This cancellation is fully completed and closed. Editing is locked.")
        return redirect("cancelled_plots_list")
        
    action = request.POST.get("action")
    if action == "finalize":
        plot.closure_status = "CLOSED"
        plot.released_for_rebooking = True
        plot.refund_status = "COMPLETED"
        plot.save()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": "Cancellation finalized and plot released for rebooking."})
        messages.success(request, "Cancellation finalized and plot released.")
        return redirect("cancelled_plots_list")
    
    if plot.closure_status == "CLOSED":
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "error", "message": "This cancellation is closed. Editing is locked."})
        messages.error(request, "This cancellation is closed. Editing is locked.")
        return redirect("cancelled_plots_list")
        
    status = request.POST.get("refund_status")
    amount = request.POST.get("refund_amount_paid", "0")
    notes = request.POST.get("refund_notes", "")
    
    if status:
        plot.refund_status = status
    if amount:
        try:
            plot.refund_amount_paid = Decimal(amount)
        except:
            return JsonResponse({"status": "error", "message": "Invalid amount"})
    plot.refund_notes = notes
    plot.save()
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({"status": "success", "message": "Refund status updated successfully."})
    messages.success(request, "Refund status updated successfully.")
    return redirect("cancelled_plots_list")


@login_required
@require_POST
@transaction.atomic
def cancelled_plot_delete(request, cp_id):
    if not request.user.has_any_role("admin", "accounts"):
        return HttpResponseForbidden("Only admin and accounts can delete cancellation records.")

    from .models import CancelledPlot

    plot = get_object_or_404(CancelledPlot, pk=cp_id)
    booking = plot.b_id
    booking_no = booking.booking_no
    plot.delete()

    if booking.status == BookingMaster.BookingStatus.CANCELLED:
        booking.status = BookingMaster.BookingStatus.ACTIVE
        booking.save(update_fields=["status"])

    msg = f"Cancellation record for booking {booking_no} deleted."
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "success", "message": msg})
    messages.success(request, msg)
    return redirect("cancelled_plots_list")


@login_required
def agent_report(request, role):
    from saas.tenant import get_booking_agent_settings_for_request, tenant_agents, tenant_bookings

    agent_settings = get_booking_agent_settings_for_request(request)
    if role in ("manager", "executive", "telecaller") and not agent_settings.is_role_enabled(role):
        return HttpResponseForbidden("This agent report is disabled in Store Settings.")

    from accounts.models import Users
    from .models import AgentMaster
    with connection.cursor() as cursor:
        agent_master_columns = {
            col.name for col in connection.introspection.get_table_description(cursor, AgentMaster._meta.db_table)
        }
    has_effective_date = "effective_date" in agent_master_columns
    has_payment_method = "payment_method" in agent_master_columns

    agents = tenant_agents(request).filter(role=role).select_related('u_id')
    defer_fields = []
    if not has_effective_date:
        defer_fields.append("effective_date")
    if not has_payment_method:
        defer_fields.append("payment_method")
    if defer_fields:
        agents = agents.defer(*defer_fields)

    agent_id = request.GET.get('agent')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    bookings = []
    total_val = 0
    total_paid = 0
    total_commission = Decimal("0.00")
    total_tds_debit = Decimal("0.00")
    total_security_pct_debit = Decimal("0.00")
    total_commission_debit = Decimal("0.00")
    total_withdrawal_commission = Decimal("0.00")
    total_withdrawal_security = Decimal("0.00")
    total_balance = Decimal("0.00")
    total_balance_type = "CR"
    total_net_credit = Decimal("0.00")
    total_debits_paid = Decimal("0.00")
    approved_withdrawn = 0
    pending_withdrawals = 0
    available_balance = 0
    commission_payments = []
    security_payments = []
    account_ledger = []
    tds_pct = Decimal("0.00")
    security_pct = Decimal("0.00")

    if agent_id:
        if role == 'manager':
            bookings = tenant_bookings(request).filter(manager_u_id=agent_id)
        elif role == 'executive':
            bookings = tenant_bookings(request).filter(executive_u_id=agent_id)
        elif role == 'telecaller':
            bookings = tenant_bookings(request).filter(telecaller_u_id=agent_id)

        bookings = bookings.exclude(status='CANCELLED').select_related(
            'u_id', 'balance', 'p_id'
        ).prefetch_related('items')

        if from_date:
            bookings = bookings.filter(booking_date__gte=from_date)
        if to_date:
            bookings = bookings.filter(booking_date__lte=to_date)

        accounts_query = tenant_agents(request).filter(u_id_id=agent_id, role='accounts')
        if defer_fields:
            accounts_query = accounts_query.defer(*defer_fields)
        accounts_entry = accounts_query.prefetch_related("debit_payments").first()
        from .models import AccountsDebitPayment

        if accounts_entry:
            for p in accounts_entry.debit_payments.all():
                if p.debit_type == AccountsDebitPayment.DebitType.COMMISSION:
                    commission_payments.append(p)
                elif p.debit_type == AccountsDebitPayment.DebitType.SECURITY:
                    security_payments.append(p)
        accounts_commission_debit, accounts_security_debit = _accounts_debit_totals(accounts_entry)

        # Use the agent's own profile settings from Add Manager / Add Executive / Add Telecaller.
        agent_profile_query = tenant_agents(request).filter(u_id_id=agent_id, role=role)
        if defer_fields:
            agent_profile_query = agent_profile_query.defer(*defer_fields)
        agent_profile = agent_profile_query.first()
        tds_pct = agent_profile.tds_amount if agent_profile else Decimal("0.00")
        security_pct = agent_profile.security_amount if agent_profile else Decimal("0.00")

        for b in bookings:
            total_val += b.balance.total_amount
            total_paid += b.balance.paid_amount
            if role == 'manager':
                pct = b.manager_percentage
            elif role == 'executive':
                pct = b.executive_percentage
            else:
                pct = b.telecaller_percentage

            b.commission_amount = (b.balance.paid_amount * pct) / 100 if pct else Decimal("0.00")
            b.commission_percentage_display = pct
            b.tds_debit = (b.commission_amount * tds_pct) / 100 if tds_pct else Decimal("0.00")
            b.security_pct_debit = (b.commission_amount * security_pct) / 100 if security_pct else Decimal("0.00")
            b.row_balance = b.commission_amount - b.tds_debit - b.security_pct_debit
            b.balance_type = "CR" if b.row_balance >= 0 else "DR"
            total_commission += b.commission_amount
            total_tds_debit += b.tds_debit
            total_security_pct_debit += b.security_pct_debit

        total_commission_debit = accounts_commission_debit
        total_withdrawal_security = accounts_security_debit
        total_withdrawal_commission = Decimal("0.00")
        total_debits_paid = total_commission_debit + total_withdrawal_security
        total_balance = (
            total_commission
            - total_tds_debit
            - total_security_pct_debit
            - total_commission_debit
            - total_withdrawal_security
        )
        total_balance_type = "CR" if total_balance >= 0 else "DR"
        total_net_credit = total_commission - total_tds_debit - total_security_pct_debit

        ledger_rows = []
        for b in bookings:
            net_credit = b.commission_amount - b.tds_debit - b.security_pct_debit
            ledger_rows.append(
                {
                    "date": b.booking_date,
                    "particulars": f"Commission earned — {b.booking_no}",
                    "debit": Decimal("0.00"),
                    "credit": net_credit,
                }
            )
        for p in commission_payments:
            ledger_rows.append(
                {
                    "date": p.payment_date,
                    "particulars": f"Commission paid ({p.get_payment_method_display()})",
                    "debit": p.amount,
                    "credit": Decimal("0.00"),
                }
            )
        for p in security_payments:
            ledger_rows.append(
                {
                    "date": p.payment_date,
                    "particulars": f"Security deposit paid ({p.get_payment_method_display()})",
                    "debit": p.amount,
                    "credit": Decimal("0.00"),
                }
            )
        ledger_rows.sort(key=lambda row: (row["date"] or date.min))
        running_ledger_balance = Decimal("0.00")
        for row in ledger_rows:
            running_ledger_balance += row["credit"] - row["debit"]
            row["balance"] = running_ledger_balance
            row["balance_type"] = "CR" if running_ledger_balance >= 0 else "DR"
        account_ledger = ledger_rows

        approved_withdrawn = IncentiveWithdrawalRequest.objects.filter(
            requested_by_id=agent_id,
            status=IncentiveWithdrawalRequest.Status.APPROVED,
        ).aggregate(total=Sum('amount'))['total'] or 0
        pending_withdrawals = IncentiveWithdrawalRequest.objects.filter(
            requested_by_id=agent_id,
            status=IncentiveWithdrawalRequest.Status.PENDING,
        ).aggregate(total=Sum('amount'))['total'] or 0
        available_balance = total_commission - approved_withdrawn - pending_withdrawals
        if available_balance < 0:
            available_balance = 0

    role_display = role.capitalize()

    return render(request, "bookings/agent_report.html", {
        "agents": agents,
        "bookings": bookings,
        "total_val": total_val,
        "total_paid": total_paid,
        "total_commission": total_commission,
        "total_tds_debit": total_tds_debit,
        "total_security_pct_debit": total_security_pct_debit,
        "total_commission_debit": total_commission_debit,
        "total_withdrawal_commission": total_withdrawal_commission,
        "total_withdrawal_security": total_withdrawal_security,
        "total_balance": total_balance,
        "total_balance_type": total_balance_type,
        "total_net_credit": total_net_credit,
        "total_debits_paid": total_debits_paid,
        "tds_pct": tds_pct if agent_id else Decimal("0.00"),
        "security_pct": security_pct if agent_id else Decimal("0.00"),
        "approved_withdrawn": approved_withdrawn,
        "pending_withdrawals": pending_withdrawals,
        "available_balance": available_balance,
        "selected_agent": agent_id,
        "from_date": from_date,
        "to_date": to_date,
        "role": role,
        "role_display": role_display,
        "commission_payments": commission_payments if agent_id else [],
        "security_payments": security_payments if agent_id else [],
        "account_ledger": account_ledger,
        "page_title": f"{role_display} Report"
    })


@login_required
def team_report(request):
    """Manager team report: bookings with manager, executive, telecaller commission merged."""
    from accounts.models import Users
    from saas.tenant import tenant_agents, tenant_bookings, tenant_users

    managers = (
        tenant_agents(request).filter(role=AgentMaster.Role.MANAGER)
        .select_related("u_id")
        .order_by("u_id__full_name")
    )

    manager_id = request.GET.get("manager")
    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")

    bookings = []
    profile_cache = {}
    team_debit_breakdown = []
    total_paid = Decimal("0.00")
    total_team_commission = Decimal("0.00")
    total_team_tds = Decimal("0.00")
    total_team_security = Decimal("0.00")
    total_commission_debit = Decimal("0.00")
    total_security_debit = Decimal("0.00")
    total_balance = Decimal("0.00")
    total_balance_type = "CR"
    total_team_net = Decimal("0.00")
    total_manager_commission = Decimal("0.00")
    total_executive_commission = Decimal("0.00")
    total_telecaller_commission = Decimal("0.00")
    team_executive_names = []
    team_telecaller_names = []
    selected_manager = None

    if manager_id:
        selected_manager = get_object_or_404(
            tenant_users(request).filter_by_role("manager"), pk=manager_id
        )
        bookings_qs = (
            tenant_bookings(request).filter(manager_u_id=manager_id)
            .exclude(status="CANCELLED")
            .select_related(
                "u_id",
                "balance",
                "p_id",
                "manager_u_id",
                "executive_u_id",
                "telecaller_u_id",
            )
            .prefetch_related("items")
            .order_by("-booking_date", "-b_id")
        )
        if from_date:
            bookings_qs = bookings_qs.filter(booking_date__gte=from_date)
        if to_date:
            bookings_qs = bookings_qs.filter(booking_date__lte=to_date)
        bookings = list(bookings_qs)
        executive_names_map = {}
        telecaller_names_map = {}

        for booking in bookings:
            paid = booking.balance.paid_amount if booking.balance else Decimal("0.00")
            total_paid += paid

            mgr_comm = _booking_commission(paid, booking.manager_percentage)
            exec_comm = _booking_commission(paid, booking.executive_percentage)
            tel_comm = _booking_commission(paid, booking.telecaller_percentage)

            mgr_profile = _agent_role_profile(
                booking.manager_u_id_id, AgentMaster.Role.MANAGER, profile_cache, request
            )
            exec_profile = _agent_role_profile(
                booking.executive_u_id_id, AgentMaster.Role.EXECUTIVE, profile_cache, request
            )
            tel_profile = _agent_role_profile(
                booking.telecaller_u_id_id, AgentMaster.Role.TELECALLER, profile_cache, request
            )

            mgr_tds_pct = mgr_profile.tds_amount if mgr_profile else Decimal("0.00")
            mgr_sec_pct = mgr_profile.security_amount if mgr_profile else Decimal("0.00")
            exec_tds_pct = exec_profile.tds_amount if exec_profile else Decimal("0.00")
            exec_sec_pct = exec_profile.security_amount if exec_profile else Decimal("0.00")
            tel_tds_pct = tel_profile.tds_amount if tel_profile else Decimal("0.00")
            tel_sec_pct = tel_profile.security_amount if tel_profile else Decimal("0.00")

            booking.manager_name = (
                booking.manager_u_id.full_name if booking.manager_u_id else "—"
            )
            booking.executive_name = (
                booking.executive_u_id.full_name if booking.executive_u_id else "—"
            )
            booking.telecaller_name = (
                booking.telecaller_u_id.full_name if booking.telecaller_u_id else "—"
            )
            booking.manager_pct = booking.manager_percentage or Decimal("0.00")
            booking.executive_pct = booking.executive_percentage or Decimal("0.00")
            booking.telecaller_pct = booking.telecaller_percentage or Decimal("0.00")
            booking.manager_commission = mgr_comm
            booking.executive_commission = exec_comm
            booking.telecaller_commission = tel_comm
            booking.manager_tds = (mgr_comm * mgr_tds_pct) / 100 if mgr_tds_pct else Decimal("0.00")
            booking.manager_security = (mgr_comm * mgr_sec_pct) / 100 if mgr_sec_pct else Decimal("0.00")
            booking.executive_tds = (exec_comm * exec_tds_pct) / 100 if exec_tds_pct else Decimal("0.00")
            booking.executive_security = (exec_comm * exec_sec_pct) / 100 if exec_sec_pct else Decimal("0.00")
            booking.telecaller_tds = (tel_comm * tel_tds_pct) / 100 if tel_tds_pct else Decimal("0.00")
            booking.telecaller_security = (tel_comm * tel_sec_pct) / 100 if tel_sec_pct else Decimal("0.00")

            booking.team_commission = mgr_comm + exec_comm + tel_comm
            booking.team_tds = (
                booking.manager_tds + booking.executive_tds + booking.telecaller_tds
            )
            booking.team_security = (
                booking.manager_security
                + booking.executive_security
                + booking.telecaller_security
            )
            booking.team_net = booking.team_commission - booking.team_tds - booking.team_security

            total_team_commission += booking.team_commission
            total_team_tds += booking.team_tds
            total_team_security += booking.team_security
            total_manager_commission += booking.manager_commission
            total_executive_commission += booking.executive_commission
            total_telecaller_commission += booking.telecaller_commission
            if booking.executive_u_id_id and booking.executive_name != "—":
                executive_names_map[booking.executive_u_id_id] = booking.executive_name
            if booking.telecaller_u_id_id and booking.telecaller_name != "—":
                telecaller_names_map[booking.telecaller_u_id_id] = booking.telecaller_name

        team_executive_names = sorted(executive_names_map.values())
        team_telecaller_names = sorted(telecaller_names_map.values())

        team_debit_breakdown, total_commission_debit, total_security_debit = _team_member_summary(
            bookings, profile_cache, request
        )
        total_team_net = total_team_commission - total_team_tds - total_team_security
        total_balance = (
            total_team_commission
            - total_team_tds
            - total_team_security
            - total_commission_debit
            - total_security_debit
        )
        total_balance_type = "CR" if total_balance >= 0 else "DR"

    return render(
        request,
        "bookings/team_report.html",
        {
            "managers": managers,
            "selected_manager": selected_manager,
            "manager_id": manager_id,
            "from_date": from_date,
            "to_date": to_date,
            "bookings": bookings,
            "team_debit_breakdown": team_debit_breakdown,
            "total_paid": total_paid,
            "total_team_commission": total_team_commission,
            "total_team_tds": total_team_tds,
            "total_team_security": total_team_security,
            "total_team_net": total_team_net,
            "total_manager_commission": total_manager_commission,
            "total_executive_commission": total_executive_commission,
            "total_telecaller_commission": total_telecaller_commission,
            "team_executive_names": team_executive_names,
            "team_telecaller_names": team_telecaller_names,
            "total_commission_debit": total_commission_debit,
            "total_security_debit": total_security_debit,
            "total_balance": total_balance,
            "total_balance_type": total_balance_type,
            "page_title": "Team Report",
        },
    )


@login_required
def incentive_withdrawal(request):
    """Agent withdrawal submission for manager/executive/telecaller and admin approval dashboard."""
    from accounts.models import Users, users_with_any_role_query
    user_role = request.user.role
    is_admin = request.user.has_role("admin")
    is_agent = request.user.has_any_role("manager", "executive", "telecaller")

    if not (is_admin or is_agent):
        return HttpResponseForbidden("Access denied. Only admin and eligible agents can access incentive withdrawals.")

    if is_admin:
        from accounts.models import Users
        all_requests = IncentiveWithdrawalRequest.objects.select_related("requested_by", "processed_by").order_by("-requested_at")
        status_filter = request.GET.get("status")
        display_requests = all_requests
        if status_filter:
            display_requests = display_requests.filter(status=status_filter)

        # All eligible agents for the withdrawal form dropdown
        agent_users = Users.objects.filter(
            users_with_any_role_query("manager", "executive", "telecaller")
        ).distinct().order_by("full_name")

        if request.method == "POST":
            request_id = request.POST.get("request_id")
            action = request.POST.get("action")
            remarks = request.POST.get("remarks", "").strip()

            if request_id and action:
                withdrawal_request = get_object_or_404(IncentiveWithdrawalRequest, pk=request_id)
                if withdrawal_request.status != IncentiveWithdrawalRequest.Status.PENDING:
                    messages.warning(request, "Only pending requests can be approved or rejected.")
                else:
                    if action == "approve":
                        withdrawal_request.status = IncentiveWithdrawalRequest.Status.APPROVED
                    elif action == "reject":
                        withdrawal_request.status = IncentiveWithdrawalRequest.Status.REJECTED
                    else:
                        messages.error(request, "Invalid approval action.")
                        return redirect('incentive_withdrawal')

                    withdrawal_request.processed_by = request.user
                    withdrawal_request.processed_at = timezone.now()
                    withdrawal_request.remarks = remarks
                    withdrawal_request.save()
                    messages.success(request, f"Withdrawal request #{withdrawal_request.iwr_id} {withdrawal_request.status.lower()}.")
                return redirect('incentive_withdrawal')

            # Admin creates withdrawal on behalf of an agent
            target_user_id = request.POST.get('target_user_id')
            if target_user_id:
                try:
                    target_user = get_object_or_404(Users, pk=target_user_id)
                    net_amount = Decimal(request.POST.get('net_amount', '0') or '0')
                    withdrawal_remarks = request.POST.get('remarks', '')
                    if net_amount <= 0:
                        messages.error(request, "Net withdrawal amount must be greater than zero.")
                    else:
                        IncentiveWithdrawalRequest.objects.create(
                            requested_by=target_user,
                            role=target_user.role,
                            amount=net_amount,
                            remarks=withdrawal_remarks,
                        )
                        messages.success(request, f"Withdrawal of ₹{net_amount} created for {target_user.full_name}.")
                        return redirect('incentive_withdrawal')
                except (ValueError, TypeError, InvalidOperation):
                    messages.error(request, "Invalid withdrawal amount.")

        total_requested = all_requests.aggregate(total=Sum('amount'))['total'] or 0
        total_approved = all_requests.filter(status=IncentiveWithdrawalRequest.Status.APPROVED).aggregate(total=Sum('amount'))['total'] or 0
        total_pending = all_requests.filter(status=IncentiveWithdrawalRequest.Status.PENDING).aggregate(total=Sum('amount'))['total'] or 0
        total_rejected = all_requests.filter(status=IncentiveWithdrawalRequest.Status.REJECTED).aggregate(total=Sum('amount'))['total'] or 0

        context = {
            "withdrawal_requests": display_requests,
            "total_requested": total_requested,
            "total_approved": total_approved,
            "total_pending": total_pending,
            "total_rejected": total_rejected,
            "status_filter": status_filter,
            "agent_users": agent_users,
            "page_title": "Incentive Withdrawal Requests",
        }
        return render(request, "bookings/incentive_withdrawal_admin.html", context)

    # Agent view
    withdrawal_requests = IncentiveWithdrawalRequest.objects.filter(requested_by=request.user).order_by("-requested_at")
    bookings = BookingMaster.objects.exclude(status="CANCELLED")

    if user_role == "manager":
        bookings = bookings.filter(manager_u_id=request.user)
    elif user_role == "executive":
        bookings = bookings.filter(executive_u_id=request.user)
    elif user_role == "telecaller":
        bookings = bookings.filter(telecaller_u_id=request.user)

    total_commission = Decimal("0.00")
    for b in bookings.select_related('balance'):
        paid_amount = b.balance.paid_amount if hasattr(b, 'balance') else Decimal("0.00")
        pct = b.manager_percentage if user_role == "manager" else b.executive_percentage if user_role == "executive" else b.telecaller_percentage
        total_commission += (paid_amount * pct) / Decimal("100.00") if pct else Decimal("0.00")

    total_withdrawn = withdrawal_requests.filter(status=IncentiveWithdrawalRequest.Status.APPROVED).aggregate(total=Sum('amount'))['total'] or Decimal("0.00")
    pending_withdrawals = withdrawal_requests.filter(status=IncentiveWithdrawalRequest.Status.PENDING).aggregate(total=Sum('amount'))['total'] or Decimal("0.00")
    available_balance = total_commission - total_withdrawn - pending_withdrawals
    if available_balance < Decimal("0.00"):
        available_balance = Decimal("0.00")

    if request.method == "POST":
        withdrawal_amount = request.POST.get('withdrawal_amount')
        remarks = request.POST.get('remarks', "")
        proof_image = request.FILES.get('proof_image')
        try:
            withdrawal_amount = Decimal(withdrawal_amount)
            if withdrawal_amount <= 0:
                messages.error(request, "Withdrawal amount must be greater than zero.")
            elif withdrawal_amount > available_balance:
                messages.error(request, "Withdrawal amount exceeds available commission balance.")
            else:
                IncentiveWithdrawalRequest.objects.create(
                    requested_by=request.user,
                    role=user_role,
                    amount=withdrawal_amount,
                    remarks=remarks,
                    proof_image=proof_image,
                )
                messages.success(request, f"Withdrawal request of ₹{withdrawal_amount} submitted successfully.")
                return redirect('incentive_withdrawal')
        except (ValueError, TypeError, InvalidOperation):
            messages.error(request, "Invalid withdrawal amount.")

    context = {
        "agent": request.user,
        "withdrawal_requests": withdrawal_requests,
        "total_commission_earned": total_commission,
        "total_withdrawn": total_withdrawn,
        "pending_withdrawals": pending_withdrawals,
        "available_balance": available_balance,
        "page_title": "Incentive Withdrawal",
    }
    return render(request, "bookings/incentive_withdrawal.html", context)
