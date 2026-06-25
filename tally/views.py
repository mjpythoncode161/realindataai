from __future__ import annotations

from decimal import Decimal, InvalidOperation
from itertools import zip_longest

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import Users, users_with_any_role_query
from saas.tenant import get_request_organization, tenant_ledgers, tenant_vouchers
from .models import LedgerMaster, Voucher, VoucherEntry


def _org(request):
    return get_request_organization(request)


def _ensure_system_ledgers(request):
    """Auto-create default system bank/cash accounts per organization."""
    org = _org(request)
    if not org:
        return
    defaults = [
        {"name": "Bank Account", "group": "BANK_CASH", "opening_balance_type": "Dr"},
        {"name": "Cash in Hand", "group": "BANK_CASH", "opening_balance_type": "Dr"},
    ]
    for d in defaults:
        LedgerMaster.objects.get_or_create(
            organization=org,
            name=d["name"],
            defaults={
                "group": d["group"],
                "opening_balance_type": d["opening_balance_type"],
                "is_system": True,
            },
        )


def _ensure_staff_ledgers(request):
    """Auto-create a LedgerMaster for every active staff user in this org."""
    org = _org(request)
    if not org:
        return
    staff = Users.objects.filter(
        users_with_any_role_query("manager", "executive", "telecaller"),
        is_active=True,
        organization=org,
    ).distinct()
    for user in staff:
        label = f"{user.full_name or user.username} ({user.get_roles_display()})"
        LedgerMaster.objects.get_or_create(
            organization=org,
            name=label,
            defaults={"group": "STAFF", "opening_balance_type": "Dr"},
        )


GROUP_META = {
    "BANK_CASH": ("Assets", "success", "Cash & Bank"),
    "ASSET": ("Assets", "success", "Fixed Assets"),
    "LIABILITY": ("Liability", "danger", "Current Liability"),
    "INCOME": ("Income", "info", "Direct Income"),
    "EXPENSE": ("Expenses", "warning", "Direct Expenses"),
    "CAPITAL": ("Capital", "primary", "Owner's Equity"),
    "STAFF": ("Expenses", "warning", "Staff & Commission"),
}


def _grouped_ledgers(request):
    _ensure_system_ledgers(request)
    _ensure_staff_ledgers(request)
    active = tenant_ledgers(request).filter(is_active=True).order_by("name")
    return (
        active.filter(group="BANK_CASH"),
        active.filter(group="STAFF"),
        active.exclude(group__in=("BANK_CASH", "STAFF")),
    )


def _tally_allowed(user):
    return user.has_any_role("admin", "accounts")


def _require_tally(view_func):
    def wrapper(request, *args, **kwargs):
        if not _tally_allowed(request.user):
            return HttpResponseForbidden("Access denied.")
        return view_func(request, *args, **kwargs)

    wrapper.__name__ = view_func.__name__
    return wrapper


@login_required
@_require_tally
def master_list(request):
    _ensure_system_ledgers(request)
    _ensure_staff_ledgers(request)

    group_order = ["BANK_CASH", "ASSET", "LIABILITY", "INCOME", "EXPENSE", "CAPITAL", "STAFF"]
    sections = []
    for gkey in group_order:
        ledgers_in_group = tenant_ledgers(request).filter(group=gkey, is_active=True).order_by("name")
        if not ledgers_in_group.exists():
            continue
        meta = GROUP_META.get(gkey, ("Other", "secondary", gkey))
        rows = []
        for idx, l in enumerate(ledgers_in_group, 1):
            bal = l.current_balance()
            rows.append({
                "num": idx,
                "ledger": l,
                "balance": abs(bal),
                "balance_type": "Dr" if bal >= 0 else "Cr",
            })
        sections.append({
            "group_key": gkey,
            "category": meta[0],
            "badge": meta[1],
            "subgroup": meta[2],
            "rows": rows,
        })

    return render(request, "tally/master_list.html", {
        "sections": sections,
        "page_title": "Ledger Master",
    })


@login_required
@_require_tally
def create_master(request):
    org = _org(request)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        group = request.POST.get("group", "")
        ob = request.POST.get("opening_balance", "0") or "0"
        ob_type = request.POST.get("opening_balance_type", "Dr")
        desc = request.POST.get("description", "")

        if not org:
            messages.error(request, "No organization linked to your account.")
        elif not name:
            messages.error(request, "Ledger name is required.")
        elif tenant_ledgers(request).filter(name__iexact=name).exists():
            messages.error(request, f"Ledger '{name}' already exists.")
        else:
            try:
                LedgerMaster.objects.create(
                    organization=org,
                    name=name,
                    group=group,
                    opening_balance=Decimal(ob),
                    opening_balance_type=ob_type,
                    description=desc,
                )
                messages.success(request, f"Ledger '{name}' created.")
                return redirect("tally_master_list")
            except (ValueError, InvalidOperation):
                messages.error(request, "Invalid opening balance.")

    return render(request, "tally/create_master.html", {
        "group_choices": LedgerMaster.GROUP_CHOICES,
        "page_title": "Create Ledger Master",
    })


@login_required
@_require_tally
def edit_master(request, l_id):
    ledger = get_object_or_404(tenant_ledgers(request), pk=l_id)
    if request.method == "POST":
        ledger.name = request.POST.get("name", ledger.name).strip()
        ledger.group = request.POST.get("group", ledger.group)
        ledger.opening_balance_type = request.POST.get("opening_balance_type", ledger.opening_balance_type)
        ledger.description = request.POST.get("description", "")
        try:
            ledger.opening_balance = Decimal(request.POST.get("opening_balance", "0") or "0")
            ledger.save()
            messages.success(request, f"Ledger '{ledger.name}' updated.")
            return redirect("tally_master_list")
        except (ValueError, InvalidOperation):
            messages.error(request, "Invalid opening balance.")

    return render(request, "tally/edit_master.html", {
        "ledger": ledger,
        "group_choices": LedgerMaster.GROUP_CHOICES,
        "page_title": "Edit Ledger Master",
    })


@login_required
@_require_tally
def delete_master(request, l_id):
    ledger = get_object_or_404(tenant_ledgers(request), pk=l_id)
    if request.method == "POST":
        if ledger.is_system:
            messages.error(request, "Cannot delete a system ledger account.")
        elif ledger.entries.exists():
            messages.error(request, "Cannot delete: ledger has existing transactions.")
        else:
            ledger.delete()
            messages.success(request, "Ledger deleted.")
    return redirect("tally_master_list")


VOUCHER_UI = {
    "PAYMENT": {
        "page_title": "Payment Voucher",
        "form_heading": "New Payment Voucher",
        "card_class": "card-danger",
        "card_icon": "fas fa-arrow-circle-up text-danger",
        "btn_class": "btn-primary ll-btn-primary",
        "save_label": "SAVE VOUCHER",
        "redirect": "tally_payment_voucher",
        "default_rows": [{"drcr": "Dr"}, {"drcr": "Cr"}],
    },
    "RECEIPT": {
        "page_title": "Receipt Voucher",
        "form_heading": "New Receipt Voucher",
        "card_class": "card-success",
        "card_icon": "fas fa-arrow-circle-down text-success",
        "btn_class": "btn-primary ll-btn-primary",
        "save_label": "SAVE VOUCHER",
        "redirect": "tally_receipt_voucher",
        "reference_label": "Reference No (optional)",
        "reference_prefix": "Ref",
        "default_rows": [{"drcr": "Dr"}, {"drcr": "Cr"}],
    },
    "JOURNAL": {
        "page_title": "Journal Entry",
        "form_heading": "New Journal Entry",
        "card_class": "card-info",
        "card_icon": "fas fa-book text-info",
        "btn_class": "btn-info",
        "save_label": "Save Journal Entry",
        "redirect": "tally_journal_entry",
        "default_rows": [{"drcr": "Dr"}, {"drcr": "Cr"}],
    },
}


def _signed_opening(ledger):
    amount = ledger.opening_balance
    return amount if ledger.opening_balance_type == "Dr" else -amount


def _balance_display(signed_amount):
    return abs(signed_amount), "Dr" if signed_amount >= 0 else "Cr"


def _parse_voucher_rows(request):
    entry_ledgers = request.POST.getlist("entry_ledger[]")
    entry_drcr = request.POST.getlist("entry_drcr[]")
    entry_amts = request.POST.getlist("entry_amount[]")
    entry_notes = request.POST.getlist("entry_note[]")

    org_ledger_ids = set(tenant_ledgers(request).values_list("pk", flat=True))
    total_dr = Decimal("0.00")
    total_cr = Decimal("0.00")
    rows = []
    for lid, drcr, amt, note in zip_longest(entry_ledgers, entry_drcr, entry_amts, entry_notes, fillvalue=""):
        amt_d = Decimal(amt or "0")
        if lid and amt_d > 0:
            lid_int = int(lid)
            if lid_int not in org_ledger_ids:
                continue
            rows.append((lid_int, drcr, amt_d, (note or "").strip()))
            if drcr == "Dr":
                total_dr += amt_d
            else:
                total_cr += amt_d
    return rows, total_dr, total_cr


def _preview_voucher_no(request, voucher_type):
    org = _org(request)
    prefix = {"PAYMENT": "PAY", "RECEIPT": "REC", "JOURNAL": "JRN"}.get(voucher_type, "VCH")
    qs = tenant_vouchers(request).filter(voucher_type=voucher_type)
    if org:
        qs = qs.filter(organization=org)
    return f"{prefix}-{qs.count() + 1:04d}"


def _voucher_form_context(request, voucher_type):
    bank_cash, staff_ledgers, other_ledgers = _grouped_ledgers(request)
    ui = VOUCHER_UI[voucher_type]
    return {
        "bank_cash": bank_cash,
        "staff_ledgers": staff_ledgers,
        "other_ledgers": other_ledgers,
        "default_rows": ui["default_rows"],
        "page_title": ui["page_title"],
        "form_heading": ui["form_heading"],
        "card_class": ui["card_class"],
        "card_icon": ui["card_icon"],
        "btn_class": ui["btn_class"],
        "save_label": ui["save_label"],
        "preview_voucher_no": _preview_voucher_no(request, voucher_type),
        "reference_label": ui.get("reference_label"),
    }


def _save_voucher(request, voucher_type):
    ui = VOUCHER_UI[voucher_type]
    org = _org(request)
    if not org:
        messages.error(request, "No organization linked to your account.")
        return None
    vdate = request.POST.get("voucher_date")
    narration = (request.POST.get("narration") or "").strip()
    reference_no = (request.POST.get("reference_no") or "").strip()
    if reference_no:
        ref_label = ui.get("reference_prefix", "Ref")
        narration = f"{ref_label}: {reference_no}" + (f" — {narration}" if narration else "")

    try:
        rows, total_dr, total_cr = _parse_voucher_rows(request)
        if not rows:
            messages.error(request, "Please add at least one ledger line with amount.")
            return None
        if abs(total_dr - total_cr) > Decimal("0.01"):
            messages.error(
                request,
                f"Debit (₹{total_dr}) must equal Credit (₹{total_cr}). Please balance the entry.",
            )
            return None

        voucher = Voucher.objects.create(
            organization=org,
            voucher_type=voucher_type,
            voucher_date=vdate,
            narration=narration,
            created_by=request.user,
        )
        for lid, drcr, amt_d, note in rows:
            VoucherEntry.objects.create(
                v_id=voucher,
                ledger_id=lid,
                dr_amount=amt_d if drcr == "Dr" else Decimal("0.00"),
                cr_amount=amt_d if drcr == "Cr" else Decimal("0.00"),
                narration=note,
            )
        messages.success(request, f"{ui['page_title']} {voucher.voucher_no} saved.")
        return voucher
    except (ValueError, InvalidOperation):
        messages.error(request, "Invalid amount entered.")
        return None


@login_required
@_require_tally
@transaction.atomic
def payment_voucher(request):
    if request.method == "POST":
        if _save_voucher(request, "PAYMENT"):
            return redirect("tally_payment_voucher")
    return render(request, "tally/voucher_form.html", _voucher_form_context(request, "PAYMENT"))


@login_required
@_require_tally
@transaction.atomic
def receipt_voucher(request):
    if request.method == "POST":
        if _save_voucher(request, "RECEIPT"):
            return redirect("tally_receipt_voucher")
    return render(request, "tally/voucher_form.html", _voucher_form_context(request, "RECEIPT"))


@login_required
@_require_tally
@transaction.atomic
def journal_entry(request):
    if request.method == "POST":
        if _save_voucher(request, "JOURNAL"):
            return redirect("tally_journal_entry")
    return render(request, "tally/voucher_form.html", _voucher_form_context(request, "JOURNAL"))


@login_required
@_require_tally
def voucher_list(request):
    qs = tenant_vouchers(request).select_related("created_by").prefetch_related("entries").order_by("-voucher_date", "-v_id")
    vtype = request.GET.get("type", "")
    from_date = request.GET.get("from_date", "")
    to_date = request.GET.get("to_date", "")

    if vtype:
        qs = qs.filter(voucher_type=vtype)
    if from_date:
        qs = qs.filter(voucher_date__gte=from_date)
    if to_date:
        qs = qs.filter(voucher_date__lte=to_date)

    return render(request, "tally/voucher_list.html", {
        "vouchers": qs,
        "vtype": vtype,
        "from_date": from_date,
        "to_date": to_date,
        "type_choices": Voucher.TYPE_CHOICES,
        "page_title": "Voucher List",
    })


@login_required
@_require_tally
def voucher_detail(request, v_id):
    voucher = get_object_or_404(
        tenant_vouchers(request).prefetch_related("entries__ledger"),
        pk=v_id,
    )
    return render(request, "tally/voucher_detail.html", {
        "voucher": voucher,
        "page_title": f"Voucher – {voucher.voucher_no}",
    })


@login_required
@_require_tally
def delete_voucher(request, v_id):
    voucher = get_object_or_404(tenant_vouchers(request), pk=v_id)
    if request.method == "POST":
        no = voucher.voucher_no
        voucher.delete()
        messages.success(request, f"Voucher {no} deleted.")
    return redirect("tally_account_statement")


@login_required
@_require_tally
def account_statement(request):
    ledgers = tenant_ledgers(request).filter(is_active=True).order_by("name")
    ledger_id = request.GET.get("ledger", "")
    from_date = request.GET.get("from_date", "")
    to_date = request.GET.get("to_date", "")

    selected_ledger = None
    entries = []
    opening = Decimal("0.00")
    opening_type = "Dr"
    total_dr = Decimal("0.00")
    total_cr = Decimal("0.00")
    closing = Decimal("0.00")
    closing_type = "Dr"
    opening_label = "Opening Balance"

    if ledger_id:
        selected_ledger = get_object_or_404(tenant_ledgers(request), pk=ledger_id)
        running = _signed_opening(selected_ledger)

        prior_qs = VoucherEntry.objects.filter(ledger=selected_ledger, v_id__organization=selected_ledger.organization)
        if from_date:
            prior_qs = prior_qs.filter(v_id__voucher_date__lt=from_date)
            prior_dr = prior_qs.aggregate(t=Sum("dr_amount"))["t"] or Decimal("0.00")
            prior_cr = prior_qs.aggregate(t=Sum("cr_amount"))["t"] or Decimal("0.00")
            running += prior_dr - prior_cr
            opening, opening_type = _balance_display(running)
            opening_label = "Opening Balance (B/F)"
        else:
            opening, opening_type = _balance_display(running)
            opening_label = "Opening Balance"

        qs = (
            VoucherEntry.objects.filter(ledger=selected_ledger, v_id__organization=selected_ledger.organization)
            .select_related("v_id")
            .order_by("v_id__voucher_date", "v_id__v_id", "ve_id")
        )
        if from_date:
            qs = qs.filter(v_id__voucher_date__gte=from_date)
        if to_date:
            qs = qs.filter(v_id__voucher_date__lte=to_date)

        for e in qs:
            running += e.dr_amount - e.cr_amount
            total_dr += e.dr_amount
            total_cr += e.cr_amount
            e.running_balance = abs(running)
            e.running_balance_type = "Dr" if running >= 0 else "Cr"
            e.display_narration = e.narration or e.v_id.narration or "—"
            entries.append(e)

        closing, closing_type = _balance_display(running)

    return render(request, "tally/account_statement.html", {
        "ledgers": ledgers,
        "selected_ledger": selected_ledger,
        "entries": entries,
        "opening": opening,
        "opening_type": opening_type,
        "opening_label": opening_label,
        "total_dr": total_dr,
        "total_cr": total_cr,
        "closing": closing,
        "closing_type": closing_type,
        "from_date": from_date,
        "to_date": to_date,
        "ledger_id": ledger_id,
        "page_title": "Account Statement",
    })


@login_required
@_require_tally
def unified_ledger(request):
    data = []
    for l in tenant_ledgers(request).order_by("group", "name"):
        bal = l.current_balance()
        dr = l.entries.aggregate(t=Sum("dr_amount"))["t"] or Decimal("0.00")
        cr = l.entries.aggregate(t=Sum("cr_amount"))["t"] or Decimal("0.00")
        data.append({
            "ledger": l,
            "total_dr": dr,
            "total_cr": cr,
            "balance": abs(bal),
            "balance_type": "Dr" if bal >= 0 else "Cr",
        })

    return render(request, "tally/unified_ledger.html", {
        "ledger_data": data,
        "page_title": "Unified Ledger",
    })
