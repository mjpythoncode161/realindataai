from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Users, Customer, users_with_any_role_query, Lead
from .forms import ProfileUpdateForm, ChangePasswordForm, LandLinkSignupForm, ContactForm
from django.utils import timezone
from datetime import timedelta
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Sum, Avg
from bookings.models import BookingMaster, ReceiptMaster, BalanceMaster, Project, CancelledPlot, Payment


USER_TYPE_TO_ROLE = {
    "1": "admin",
    "2": "customer",
    "3": "executive",
    "4": "manager",
    "5": "telecaller",
    "6": "accounts",
    "7": "followup",
}

ROLE_TO_USER_TYPE = {role: user_type for user_type, role in USER_TYPE_TO_ROLE.items()}

ROLE_LABELS = {
    "admin": "Admin",
    "customer": "Customer",
    "executive": "Executive",
    "manager": "Manager",
    "telecaller": "Telecaller",
    "accounts": "Accounts",
    "followup": "Followup",
}

ROLE_OPTION_ORDER = (
    "customer",
    "admin",
    "manager",
    "executive",
    "telecaller",
    "accounts",
    "followup",
)

STAFF_ROLE_ORDER = (
    "admin",
    "manager",
    "executive",
    "telecaller",
    "accounts",
    "followup",
)


def _role_options_for(user):
    if user.has_role("admin"):
        roles = STAFF_ROLE_ORDER
    else:
        roles = ()
    return [{"key": role, "label": ROLE_LABELS[role], "type": ROLE_TO_USER_TYPE[role]} for role in roles]


def _staff_roles_from_request(request):
    return [
        role for role in request.POST.getlist("roles")
        if role in ROLE_LABELS and role != "customer"
    ]


def _role_from_user_type(user_type):
    return USER_TYPE_TO_ROLE.get((user_type or "2").strip(), "customer")


def _parse_roles_from_request(request, fallback_type="2"):
    roles = [role for role in request.POST.getlist("roles") if role in ROLE_LABELS]
    if roles:
        return roles
    user_type = (request.POST.get("type") or fallback_type).strip()
    return [_role_from_user_type(user_type)]


def _sync_customer_profile(user_obj, roles):
    role_list = roles if isinstance(roles, (list, tuple)) else [roles]
    if "customer" in role_list:
        Customer.objects.get_or_create(u_id=user_obj, defaults={"aadhar_number": ""})
    else:
        Customer.objects.filter(u_id=user_obj).delete()


def _apply_roles_to_user(user_obj, roles):
    user_obj.set_roles(roles)
    user_obj.save(update_fields=["roles", "role"])
    _sync_customer_profile(user_obj, roles)


def _redirect_authenticated_user(user):
    from saas.tenant import get_user_organization
    from saas.models import Organization

    org = get_user_organization(user)
    if org and org.status == Organization.Status.PENDING_PAYMENT:
        return redirect("saas_choose_plan")
    if org and not org.is_subscription_active:
        return redirect("subscription_expired")
    if getattr(user, "pending_signup_approval", False):
        return redirect("saas_choose_plan")
    if getattr(user, "is_trial_account", False) and not user.trial_is_active:
        return redirect("subscription_expired")
    if getattr(user, "is_superuser", False):
        return redirect("platform_dashboard")
    return redirect("home")


def _resolve_login_username(identifier):
    """Map email or phone (or username) to Django auth username."""
    raw = (identifier or "").strip()
    if not raw:
        return None
    if "@" in raw:
        user = Users.objects.filter(email__iexact=raw).only("username").first()
        return user.username if user else None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 10:
        phone = digits[-10:]
        user = Users.objects.filter(phone=phone).only("username").first()
        if user:
            return user.username
    return raw


def landing_home(request):
    if request.user.is_authenticated:
        return _redirect_authenticated_user(request.user)

    contact_form = ContactForm()
    if request.method == "POST" and request.POST.get("form_type") == "contact":
        contact_form = ContactForm(request.POST)
        if contact_form.is_valid():
            messages.success(
                request,
                "Thank you! We received your message and will contact you shortly.",
            )
            return redirect(reverse("landing_home") + "#contact")
        messages.error(request, "Please correct the errors in the contact form.")

    return render(request, "website/landing.html", {"contact_form": contact_form})


def public_signup(request):
    if request.user.is_authenticated:
        return _redirect_authenticated_user(request.user)
    form = LandLinkSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        user = Users.objects.create_user(
            username=email,
            email=email,
            full_name=form.cleaned_data["full_name"],
            phone=form.cleaned_data["phone"],
            role="manager",
            password=form.cleaned_data["password"],
            company_name=form.cleaned_data["company_name"],
            is_trial_account=False,
            signup_approved=True,
            trial_started_at=None,
            trial_ends_at=None,
            is_active=True,
        )
        auth_login(request, user)
        messages.info(
            request,
            "Account created. Choose your plan and pay to start your CRM workspace instantly.",
        )
        tier = (request.POST.get("plan_tier") or request.GET.get("plan") or "").strip().lower()
        if tier:
            return redirect(f"{reverse('saas_choose_plan')}?plan={tier}")
        return redirect("saas_choose_plan")
    from saas.services import get_active_plans
    return render(
        request,
        "website/signup.html",
        {"form": form, "plans": get_active_plans()},
    )


def pending_approval(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if not request.user.pending_signup_approval:
        return redirect("home")
    return render(request, "website/pending_approval.html")


@login_required
def followup_signup_approvals(request):
    if not request.user.has_role("followup"):
        return HttpResponseForbidden("Only Followup department can access signup approvals.")

    pending_qs = Users.objects.filter(
        is_trial_account=True, signup_approved=False, is_active=True
    ).order_by("-date_joined")
    approved_qs = Users.objects.filter(
        is_trial_account=True, signup_approved=True
    ).order_by("-signup_approved_at")[:50]

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        action = (request.POST.get("action") or "").strip().lower()
        target = get_object_or_404(
            Users, u_id=user_id, is_trial_account=True, signup_approved=False
        )
        if action == "approve":
            now = timezone.now()
            target.signup_approved = True
            target.signup_approved_at = now
            target.signup_approved_by = request.user
            target.trial_started_at = now
            target.trial_ends_at = now + timedelta(days=7)
            target.save(
                update_fields=[
                    "signup_approved",
                    "signup_approved_at",
                    "signup_approved_by",
                    "trial_started_at",
                    "trial_ends_at",
                ]
            )
            messages.success(
                request,
                f"Approved {target.full_name}. Their 7-day trial has started and they can use the dashboard.",
            )
        elif action == "reject":
            name = target.full_name
            target.is_active = False
            target.save(update_fields=["is_active"])
            messages.warning(request, f"Registration for {name} was rejected.")
        return redirect("followup_signup_approvals")

    return render(
        request,
        "accounts/followup_signup_approvals.html",
        {
            "pending_signups": pending_qs,
            "approved_signups": approved_qs,
            "pending_count": pending_qs.count(),
        },
    )


def trial_expired(request):
    if request.user.is_authenticated:
        if request.user.pending_signup_approval:
            return redirect("pending_approval")
        if request.user.is_trial_account and request.user.trial_is_active:
            return redirect("home")
    return render(request, "website/trial_expired.html")


def login_view(request):
    if request.user.is_authenticated:
        return _redirect_authenticated_user(request.user)
    if request.method == "POST":
        login_id = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        resolved = _resolve_login_username(login_id)
        if not resolved:
            messages.error(request, "No account found with that email or phone number.")
            return render(request, "accounts/login.html")
        user = authenticate(request, username=resolved, password=password)
        if user is not None:
            if not user.is_active:
                messages.error(
                    request,
                    "Your registration was not approved. Please contact Land Link support.",
                )
                return render(request, "accounts/login.html")
            if request.POST.get("remember"):
                request.session.set_expiry(60 * 60 * 24 * 14)
            else:
                request.session.set_expiry(0)
            auth_login(request, user)
            return _redirect_authenticated_user(user)
        messages.error(request, "Invalid email/phone or password.")
    return render(request, "accounts/login.html")


def _sync_customer_from_user(user):
    if not user.has_role("customer"):
        return
    customer, _ = Customer.objects.get_or_create(u_id=user, defaults={"aadhar_number": ""})
    customer.full_name = user.full_name
    customer.phone = user.phone
    customer.email = user.email
    customer.save()


@login_required
def manage_account(request):
    user = request.user
    profile_form = ProfileUpdateForm(user)
    password_form = ChangePasswordForm(user)

    if request.method == "POST":
        action = request.POST.get("action", "profile")
        if action == "profile":
            profile_form = ProfileUpdateForm(user, request.POST)
            if profile_form.is_valid():
                user.full_name = profile_form.cleaned_data["full_name"]
                user.phone = profile_form.cleaned_data["phone"]
                user.email = profile_form.cleaned_data["email"]
                user.username = profile_form.cleaned_data["email"]
                user.save()
                _sync_customer_from_user(user)
                messages.success(request, "Profile updated successfully.")
                return redirect("manage_account")
            messages.error(request, "Please correct the profile errors below.")
        elif action == "password":
            password_form = ChangePasswordForm(user, request.POST)
            if password_form.is_valid():
                user.set_password(password_form.cleaned_data["new_password"])
                user.save()
                from django.contrib.auth import update_session_auth_hash

                update_session_auth_hash(request, user)
                messages.success(request, "Password changed successfully.")
                return redirect("manage_account")
            messages.error(request, "Please correct the password errors below.")

    return render(
        request,
        "accounts/profile.html",
        {
            "profile_form": profile_form,
            "password_form": password_form,
            "role_display": user.get_role_display(),
        },
    )


@login_required
def home(request):
    if request.user.pending_signup_approval:
        return redirect("pending_approval")

    if request.user.is_superuser:
        return redirect("platform_dashboard")

    from bookings.views import base_report_queryset
    from datetime import date, timedelta
    from bookings.models import Payment
    from django.db.models import Sum
    
    today = date.today()
    
    if request.user.has_role("accounts"):
        from saas.tenant import tenant_payments

        pending_payments = tenant_payments(request).filter(status='PENDING').select_related('b_id', 'created_by').order_by('-created_at')
        approved_payments = tenant_payments(request).filter(status='APPROVED')
        
        total_approved_amount = approved_payments.aggregate(Sum('pay_amount'))['pay_amount__sum'] or 0
        
        context = {
            "user": request.user,
            "pending_payments": pending_payments[:10],  # Recent 10 for table
            "pending_payments_count": pending_payments.count(),
            "approved_payments_count": approved_payments.count(),
            "total_financial_summary": total_approved_amount,
        }
        return render(request, "accounts/accounts_dashboard.html", context)

    if request.user.has_role("customer"):
        # Customer Dashboard logic
        bookings = BookingMaster.objects.filter(u_id=request.user).select_related('p_id', 'balance', 'cancelled_details').order_by('-created_at')
        receipts = ReceiptMaster.objects.filter(b_id__u_id=request.user).order_by('-receipt_date')[:5]
        
        # Calculate financial summary
        total_value = 0
        total_paid = 0
        total_balance = 0
        for b in bookings:
            try:
                if b.status != 'CANCELLED':
                    total_value += b.balance.total_amount
                    total_paid += b.balance.paid_amount
                    total_balance += b.balance.balance_amount
            except:
                pass
        
        context = {
            "user": request.user,
            "bookings": bookings,
            "receipts": receipts,
            "total_value": total_value,
            "total_paid": total_paid,
            "total_balance": total_balance,
            "payment_progress": (total_paid / total_value * 100) if total_value > 0 else 0
        }
        return render(request, "accounts/customer_dashboard.html", context)

    # Manager / Executive / Telecaller — lead dashboard on home (not admin)
    if (
        not request.user.has_role("admin")
        and request.user.has_any_role("manager", "executive", "telecaller")
    ):
        from .lead_views import _lead_queryset_for

        lq = _lead_queryset_for(request.user).distinct()
        return render(
            request,
            "accounts/lead_dashboard.html",
            {
                "user": request.user,
                "lead_counts": {
                    "total": lq.count(),
                    "pending": lq.exclude(
                        status__in=[Lead.Status.CONFIRMED, Lead.Status.CLOSED_LOST]
                    ).count(),
                    "confirmed": lq.filter(status=Lead.Status.CONFIRMED).count(),
                    "closed": lq.filter(status=Lead.Status.CLOSED_LOST).count(),
                },
                "recent_leads": lq.order_by("-updated_at", "-lead_id")[:10],
            },
        )

    # Admin / staff home dashboard
    from saas.tenant import (
        get_request_organization,
        tenant_bookings,
        tenant_cancelled_plots,
        tenant_customers,
        tenant_payments,
        tenant_projects,
        tenant_receipts,
        tenant_staff_users,
    )

    org = get_request_organization(request)
    tb = tenant_bookings(request)
    tr = tenant_receipts(request)
    tp = tenant_payments(request)

    qs = base_report_queryset(user=request.user, organization=org)
    qs = qs.filter(payment_status='PARTIAL', final_followup_date__gte=today)

    total_revenue = tr.aggregate(Sum('pay_amount'))['pay_amount__sum'] or 0
    pending_payments_amount = tp.filter(status='PENDING').aggregate(Sum('pay_amount'))['pay_amount__sum'] or 0

    total_paid = BalanceMaster.objects.filter(b_id__in=tb.values('b_id')).aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
    total_amount_all = BalanceMaster.objects.filter(b_id__in=tb.values('b_id')).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    completion_rate = round((total_paid / total_amount_all * 100) if total_amount_all > 0 else 0, 1)

    # Real monthly booking data for chart (last 6 months)
    import json as _json
    from datetime import date as _date
    _six_months_ago = today.replace(day=1) - timedelta(days=150)
    monthly_labels = []
    monthly_booking_counts = []
    monthly_revenue_data = []
    for i in range(5, -1, -1):
        from datetime import date as _d2
        import calendar
        month_date = (today.replace(day=1) - timedelta(days=i * 30))
        m_start = month_date.replace(day=1)
        m_end = month_date.replace(day=calendar.monthrange(month_date.year, month_date.month)[1])
        monthly_labels.append(m_start.strftime("%b %Y"))
        monthly_booking_counts.append(
            tb.filter(booking_date__gte=m_start, booking_date__lte=m_end).count()
        )
        monthly_revenue_data.append(float(
            tr.filter(receipt_date__gte=m_start, receipt_date__lte=m_end)
            .aggregate(Sum('pay_amount'))['pay_amount__sum'] or 0
        ))

    project_labels = []
    project_booking_counts = []
    for proj in tenant_projects(request)[:8]:
        cnt = tb.filter(p_id=proj, status='ACTIVE').count()
        if cnt > 0:
            project_labels.append(proj.name)
            project_booking_counts.append(cnt)

    recent_bookings_qs = tb.select_related("u_id", "p_id").order_by("-booking_date")
    if request.user.has_role("manager") and not request.user.has_role("admin"):
        recent_bookings_qs = recent_bookings_qs.filter(created_by=request.user)

    context = {
        "user": request.user,
        "followups_today": qs.filter(final_followup_date=today).count(),
        "followups_7": qs.filter(final_followup_date__gt=today, final_followup_date__lte=today + timedelta(days=7)).count(),
        "followups_15": qs.filter(final_followup_date__gt=today + timedelta(days=7), final_followup_date__lte=today + timedelta(days=15)).count(),
        "followups_30": qs.filter(final_followup_date__gt=today + timedelta(days=15), final_followup_date__lte=today + timedelta(days=30)).count(),
        "total_customers": tenant_customers(request).count(),
        "total_bookings": tb.count(),
        "total_cancellations": tenant_cancelled_plots(request).count(),
        "total_projects": tenant_projects(request).count(),
        "recent_bookings": recent_bookings_qs[:8],
        "total_revenue": total_revenue,
        "pending_payments_amount": pending_payments_amount,
        "completion_rate": completion_rate,
        "monthly_labels_json": _json.dumps(monthly_labels),
        "monthly_bookings_json": _json.dumps(monthly_booking_counts),
        "monthly_revenue_json": _json.dumps(monthly_revenue_data),
        "project_labels_json": _json.dumps(project_labels),
        "project_counts_json": _json.dumps(project_booking_counts),
    }

    if request.user.has_role('admin'):
        context.update({
            "total_employees": tenant_staff_users(request).exclude(role='customer').count(),
            "pending_payments": tp.filter(status='PENDING').count(),
        })
    elif request.user.has_role('manager'):
        context["pending_payments"] = tp.filter(status='PENDING', created_by=request.user).count()

    if request.user.has_any_role("followup", "manager", "executive", "telecaller", "admin"):
        from .lead_views import _lead_queryset_for
        lq = _lead_queryset_for(request.user).distinct()
        context["lead_counts"] = {
            "total": lq.count(),
            "pending": lq.exclude(status__in=[Lead.Status.CONFIRMED, Lead.Status.CLOSED_LOST]).count(),
            "confirmed": lq.filter(status=Lead.Status.CONFIRMED).count(),
            "closed": lq.filter(status=Lead.Status.CLOSED_LOST).count(),
        }
        context["open_leads_count"] = context["lead_counts"]["pending"]
    if request.user.has_role("followup"):
        context["pending_signup_count"] = Users.objects.filter(
            is_trial_account=True, signup_approved=False, is_active=True
        ).count()

    return render(request, "accounts/dashboard.html", context)


def logout_view(request):
    auth_logout(request)
    return redirect("login")


def _parse_optional_date(value):
    from datetime import datetime

    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


@login_required
@transaction.atomic
def register_customer(request):
    if request.method == "POST":
        full_name = (request.POST.get("full_name") or "").strip()
        phone = (request.POST.get("contact") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        aadhar_number = (request.POST.get("aadhar_number") or "").strip()
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""
        date_of_birth = _parse_optional_date(request.POST.get("date_of_birth"))
        occupation = (request.POST.get("occupation") or "").strip()
        present_address = (request.POST.get("present_address") or "").strip()
        permanent_address = (request.POST.get("permanent_address") or "").strip()
        pin_code = (request.POST.get("pin_code") or "").strip()
        nominee = (request.POST.get("nominee") or "").strip()
        relationship = (request.POST.get("relationship") or "").strip()

        if not full_name or not phone or not email or not password:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Name, contact, email and password are required."})
            messages.error(request, "Name, contact, email and password are required.")
            return redirect("register_customer")
        if aadhar_number and (not aadhar_number.isdigit() or len(aadhar_number) != 12):
            msg = "Aadhaar number must be exactly 12 digits when provided."
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": msg})
            messages.error(request, msg)
            return redirect("register_customer")
        if password != confirm_password:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Passwords do not match."})
            messages.error(request, "Passwords do not match.")
            return redirect("register_customer")
        if Users.objects.filter(email=email).exists():
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Email already exists."})
            messages.error(request, "Email already exists.")
            return redirect("register_customer")
        if Users.objects.filter(phone=phone).exists():
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Phone already exists."})
            messages.error(request, "Phone already exists.")
            return redirect("register_customer")

        try:
            from saas.tenant import assign_user_to_organization, get_request_organization
            org = get_request_organization(request)
            user = Users.objects.create_user(
                username=email,
                email=email,
                full_name=full_name,
                phone=phone,
                role="customer",
                password=password,
                created_by=request.user,
                organization=org,
            )
            if org:
                assign_user_to_organization(user, org)
            Customer.objects.create(
                u_id=user,
                aadhar_number=aadhar_number,
                date_of_birth=date_of_birth,
                occupation=occupation,
                present_address=present_address,
                permanent_address=permanent_address,
                pin_code=pin_code,
                nominee=nominee,
                relationship=relationship,
            )
        except Exception as e:
            # Catch DB errors like 'Data too long'
            error_msg = str(e)
            if "aadhar_number" in error_msg.lower():
                error_msg = "Aadhaar number is too long. Please enter a valid 12-digit number."
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": error_msg})
            messages.error(request, error_msg)
            return redirect("register_customer")

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": f"Customer created successfully (User ID: {user.u_id})."})
        messages.success(
            request, f"Customer created successfully (User ID: {user.u_id})."
        )
        return redirect("customer_list")

    return render(request, "accounts/add_customer.html")


@login_required
def user_list(request):
    from saas.tenant import tenant_staff_users

    if not request.user.has_role("admin"):
        return HttpResponseForbidden("Only Admins can view User list.")
    users = tenant_staff_users(request).order_by("-u_id")
    return render(
        request,
        "accounts/user_list.html",
        {"users": users},
    )


@login_required
def customer_list(request):
    from saas.tenant import tenant_customers

    if request.user.has_role("accounts"):
        return HttpResponseForbidden("Accounts cannot access Customer list.")

    customers = tenant_customers(request).order_by("-u_id__u_id")
    if request.user.has_role("manager") and not request.user.has_role("admin"):
        customers = customers.filter(u_id__created_by=request.user)

    return render(
        request,
        "accounts/customer_list.html",
        {
            "customers": customers,
        },
    )


@login_required
@transaction.atomic
def edit_customer(request, cust_id: int):
    if request.user.has_role("accounts"):
        return HttpResponseForbidden("Accounts cannot access this page.")

    customer = get_object_or_404(Customer.objects.select_related("u_id"), pk=cust_id)
    user_obj = customer.u_id

    if request.user.has_role("manager"):
        if not user_obj.has_role("customer") or user_obj.created_by != request.user:
            return HttpResponseForbidden("You can only edit customers created by you.")

    if request.method == "POST":
        full_name = (request.POST.get("full_name") or "").strip()
        phone = (request.POST.get("contact") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        aadhar_number = (request.POST.get("aadhar_number") or "").strip()
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""
        date_of_birth = _parse_optional_date(request.POST.get("date_of_birth"))
        occupation = (request.POST.get("occupation") or "").strip()
        present_address = (request.POST.get("present_address") or "").strip()
        permanent_address = (request.POST.get("permanent_address") or "").strip()
        pin_code = (request.POST.get("pin_code") or "").strip()
        nominee = (request.POST.get("nominee") or "").strip()
        relationship = (request.POST.get("relationship") or "").strip()

        if not full_name or not phone or not email:
            msg = "Full name, phone, and email are required."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"status": "error", "message": msg})
            messages.error(request, msg)
            return redirect("edit_customer", cust_id=customer.cust_id)
        if aadhar_number and (not aadhar_number.isdigit() or len(aadhar_number) != 12):
            msg = "Aadhaar number must be exactly 12 digits when provided."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"status": "error", "message": msg})
            messages.error(request, msg)
            return redirect("edit_customer", cust_id=customer.cust_id)
        if Users.objects.exclude(u_id=user_obj.u_id).filter(email=email).exists():
            msg = "Email already exists."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"status": "error", "message": msg})
            messages.error(request, msg)
            return redirect("edit_customer", cust_id=customer.cust_id)
        if Users.objects.exclude(u_id=user_obj.u_id).filter(phone=phone).exists():
            msg = "Phone already exists."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"status": "error", "message": msg})
            messages.error(request, msg)
            return redirect("edit_customer", cust_id=customer.cust_id)
        if password and password != confirm_password:
            msg = "Passwords do not match."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"status": "error", "message": msg})
            messages.error(request, msg)
            return redirect("edit_customer", cust_id=customer.cust_id)

        user_obj.full_name = full_name
        user_obj.phone = phone
        user_obj.email = email
        user_obj.username = email
        if password:
            user_obj.set_password(password)
        user_obj.save()

        customer.aadhar_number = aadhar_number
        customer.date_of_birth = date_of_birth
        customer.occupation = occupation
        customer.present_address = present_address
        customer.permanent_address = permanent_address
        customer.pin_code = pin_code
        customer.nominee = nominee
        customer.relationship = relationship
        customer.save()

        msg = "Customer updated successfully."
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"status": "success", "message": msg})
        messages.success(request, msg)
        return redirect("customer_list")

    return render(request, "accounts/edit_customer.html", {"customer": customer})


@login_required
@transaction.atomic
def add_user(request):
    if not request.user.has_role("admin"):
        return HttpResponseForbidden("Only Admins can add staff users.")
    if request.user.has_role("accounts"):
        return HttpResponseForbidden("Accounts cannot access this page.")
    if request.method == "POST":
        full_name = (request.POST.get("full_name") or "").strip()
        phone = (request.POST.get("contact") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""
        user_type = (request.POST.get("type") or "2").strip()

        if not full_name or not phone or not email or not password:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "All fields are required."})
            messages.error(request, "All fields are required.")
            return redirect("add_user")
        if password != confirm_password:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Passwords do not match."})
            messages.error(request, "Passwords do not match.")
            return redirect("add_user")
        if Users.objects.filter(email=email).exists():
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Email already exists."})
            messages.error(request, "Email already exists.")
            return redirect("add_user")
        if Users.objects.filter(phone=phone).exists():
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Phone already exists."})
            messages.error(request, "Phone already exists.")
            return redirect("add_user")

        roles = _staff_roles_from_request(request)
        if not roles:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Select at least one role."})
            messages.error(request, "Select at least one role.")
            return redirect("add_user")

        user = Users.objects.create_user(
            username=email,
            email=email,
            full_name=full_name,
            phone=phone,
            role=Users._primary_role(roles),
            password=password,
            created_by=request.user,
        )
        user.set_roles(roles)
        user.save(update_fields=["roles", "role"])
        from saas.tenant import assign_user_to_organization, get_request_organization
        org = get_request_organization(request)
        if org:
            assign_user_to_organization(user, org)
        _sync_customer_profile(user, roles)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": f"User created successfully (User ID: {user.u_id})."})
        messages.success(request, f"User created successfully (User ID: {user.u_id}).")
        return redirect("user_list")

    return render(
        request,
        "accounts/add_user.html",
        {"role_options": _role_options_for(request.user)},
    )


@login_required
@transaction.atomic
def edit_user(request, user_id: int):
    if request.user.has_role("accounts"):
        return HttpResponseForbidden("Accounts cannot access this page.")
        
    user_obj = get_object_or_404(Users, u_id=user_id)

    if user_obj.has_role("customer"):
        customer = Customer.objects.filter(u_id=user_obj).first()
        if customer:
            return redirect("edit_customer", cust_id=customer.cust_id)
    
    if request.user.has_role("manager"):
        if user_obj.role != "customer" or user_obj.created_by != request.user:
             return HttpResponseForbidden("You can only edit customers created by you.")

    if request.method == "POST":
        full_name = (request.POST.get("full_name") or "").strip()
        phone = (request.POST.get("contact") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""
        user_type = (request.POST.get("type") or "2").strip()

        if not full_name or not phone or not email:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Full name, phone, and email are required."})
            messages.error(request, "Full name, phone, and email are required.")
            return redirect("edit_user", user_id=user_obj.u_id)
        if Users.objects.exclude(u_id=user_obj.u_id).filter(email=email).exists():
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Email already exists."})
            messages.error(request, "Email already exists.")
            return redirect("edit_user", user_id=user_obj.u_id)
        if Users.objects.exclude(u_id=user_obj.u_id).filter(phone=phone).exists():
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Phone already exists."})
            messages.error(request, "Phone already exists.")
            return redirect("edit_user", user_id=user_obj.u_id)
        if password and password != confirm_password:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"status": "error", "message": "Passwords do not match."})
            messages.error(request, "Passwords do not match.")
            return redirect("edit_user", user_id=user_obj.u_id)

        user_obj.full_name = full_name
        user_obj.phone = phone
        user_obj.email = email
        user_obj.username = email
        if password:
            user_obj.set_password(password)
        user_obj.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"status": "success", "message": "User updated successfully."})
        messages.success(request, "User updated successfully.")
        return redirect("user_list")

    return render(
        request,
        "accounts/edit_user.html",
        {
            "user_obj": user_obj,
            "can_assign_role": request.user.has_role("admin"),
        },
    )


@login_required
@transaction.atomic
def assign_user_role(request, user_id: int):
    if not request.user.has_role("admin"):
        return HttpResponseForbidden("Only Admins can assign roles.")

    user_obj = get_object_or_404(Users, u_id=user_id)
    if user_obj.u_id == request.user.u_id:
        messages.error(request, "You cannot change your own roles.")
        return redirect("user_list")

    if request.method == "POST":
        roles = _staff_roles_from_request(request)
        if not roles:
            messages.error(request, "Select at least one role.")
            return redirect("assign_user_role", user_id=user_obj.u_id)

        _apply_roles_to_user(user_obj, roles)
        labels = [ROLE_LABELS[role] for role in roles]
        messages.success(
            request,
            f"Roles updated for {user_obj.full_name}: {', '.join(labels)}.",
        )
        return redirect("user_list")

    return render(
        request,
        "accounts/assign_user_roles.html",
        {
            "user_obj": user_obj,
            "role_options": _role_options_for(request.user),
        },
    )


@login_required
@transaction.atomic
def delete_user(request, user_id: int):
    user_obj = get_object_or_404(Users, u_id=user_id)
    if user_obj.u_id == request.user.u_id:
        messages.error(request, "You cannot delete your own user.")
        return redirect("user_list")
    user_obj.delete()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({"status": "success", "message": "User deleted successfully."})
    messages.success(request, "User deleted successfully.")
    return redirect("user_list")


@login_required
def activity_log(request):
    from datetime import datetime, timedelta

    from .models import ActivityLog
    from saas.tenant import tenant_activity_logs

    if not request.user.has_role("admin"):
        return HttpResponseForbidden("Access denied.")

    logs = tenant_activity_logs(request).select_related("user").order_by("-timestamp")

    action_filter = request.GET.get("action", "")
    model_filter = request.GET.get("model", "")
    user_filter = request.GET.get("user", "")
    show_all = request.GET.get("show_all") == "1"
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    default_date_range = False

    if not show_all and not date_from and not date_to:
        today = timezone.localdate()
        date_from = (today - timedelta(days=6)).isoformat()
        date_to = today.isoformat()
        default_date_range = True

    def _parse_filter_date(value):
        if not value:
            return None
        value = value.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    if action_filter:
        logs = logs.filter(action=action_filter)
    if model_filter:
        logs = logs.filter(model_name__icontains=model_filter)
    if user_filter:
        logs = logs.filter(user__username__icontains=user_filter)
    if date_from:
        parsed_from = _parse_filter_date(date_from)
        if parsed_from:
            logs = logs.filter(timestamp__date__gte=parsed_from)
    if date_to:
        parsed_to = _parse_filter_date(date_to)
        if parsed_to:
            logs = logs.filter(timestamp__date__lte=parsed_to)

    action_choices = ActivityLog.Action.choices
    model_names = (
        tenant_activity_logs(request)
        .values_list("model_name", flat=True)
        .distinct()
        .order_by("model_name")
    )

    return render(request, "accounts/activity_log.html", {
        "logs": logs,
        "action_choices": action_choices,
        "model_names": model_names,
        "show_all": show_all,
        "default_date_range": default_date_range,
        "filters": {
            "action": action_filter,
            "model": model_filter,
            "user": user_filter,
            "date_from": date_from,
            "date_to": date_to,
        },
    })
