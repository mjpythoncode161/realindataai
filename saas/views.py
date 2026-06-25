from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from saas.models import Organization, PaymentOrder, SubscriptionPlan
from saas.services import (
    activate_after_payment,
    create_organization_for_signup,
    create_payment_order,
    get_active_plans,
    verify_razorpay_signature,
)
from saas.tenant import get_user_organization


def pricing_page(request):
    plans = get_active_plans()
    return render(request, "saas/pricing.html", {"plans": plans})


@login_required
def choose_plan(request):
    org = get_user_organization(request.user)
    if org and org.status == Organization.Status.ACTIVE and org.is_subscription_active:
        return redirect("home")

    plans = get_active_plans()
    selected = (request.GET.get("plan") or "").strip().lower()

    if request.method == "POST":
        tier = (request.POST.get("plan_tier") or "").strip().lower()
        plan = SubscriptionPlan.objects.filter(tier=tier, is_active=True).first()
        if not plan:
            messages.error(request, "Please select a valid plan.")
            return redirect("saas_choose_plan")

        if not org:
            company = request.user.company_name or request.user.full_name
            org = create_organization_for_signup(request.user, company, plan)
        else:
            org.plan = plan
            org.save(update_fields=["plan", "updated_at"])

        request.session["saas_checkout_plan"] = plan.tier
        return redirect("saas_checkout")

    return render(
        request,
        "saas/choose_plan.html",
        {"plans": plans, "organization": org, "selected_tier": selected},
    )


@login_required
def checkout(request):
    org = get_user_organization(request.user)
    if not org:
        return redirect("saas_choose_plan")

    plan = org.plan
    if not plan:
        return redirect("saas_choose_plan")

    if org.status == Organization.Status.ACTIVE and org.is_subscription_active:
        return redirect("home")

    if request.method == "POST":
        try:
            payment_order, rzp_order = create_payment_order(org, plan)
        except Exception:
            messages.error(request, "Could not start payment. Please try again or contact support.")
            return redirect("saas_checkout")

        if payment_order.is_demo:
            activate_after_payment(payment_order, razorpay_payment_id=f"demo_pay_{payment_order.uuid}")
            messages.success(
                request,
                f"Welcome! Your {plan.name} plan is active. Your workspace is ready.",
            )
            return redirect("saas_payment_success")

        request.session["saas_pending_order"] = str(payment_order.uuid)
        return render(
            request,
            "saas/checkout.html",
            {
                "organization": org,
                "plan": plan,
                "payment_order": payment_order,
                "razorpay_key_id": __import__("django.conf", fromlist=["settings"]).settings.RAZORPAY_KEY_ID,
                "amount_paise": int(plan.price_inr * 100),
            },
        )

    return render(
        request,
        "saas/checkout.html",
        {"organization": org, "plan": plan, "preview": True},
    )


@login_required
@require_POST
def payment_verify(request):
    org = get_user_organization(request.user)
    order_uuid = request.session.get("saas_pending_order") or request.POST.get("order_uuid")
    payment_order = get_object_or_404(
        PaymentOrder,
        uuid=order_uuid,
        organization=org,
        status=PaymentOrder.Status.CREATED,
    )

    razorpay_order_id = request.POST.get("razorpay_order_id", "")
    razorpay_payment_id = request.POST.get("razorpay_payment_id", "")
    razorpay_signature = request.POST.get("razorpay_signature", "")

    if not verify_razorpay_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
        payment_order.status = PaymentOrder.Status.FAILED
        payment_order.save(update_fields=["status"])
        messages.error(request, "Payment verification failed. Please contact support if amount was deducted.")
        return redirect("saas_checkout")

    activate_after_payment(payment_order, razorpay_payment_id, razorpay_signature)
    request.session.pop("saas_pending_order", None)
    messages.success(request, f"Payment successful! Your {payment_order.plan.name} plan is now active.")
    return redirect("saas_payment_success")


@login_required
def payment_success(request):
    org = get_user_organization(request.user)
    return render(request, "saas/payment_success.html", {"organization": org})


def subscription_expired(request):
    org = None
    if request.user.is_authenticated:
        org = get_user_organization(request.user)
    return render(request, "saas/subscription_expired.html", {"organization": org})


@csrf_exempt
@require_POST
def payment_webhook(request):
    """Razorpay webhook — optional server-side payment confirmation."""
    import json

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    event = payload.get("event", "")
    if event != "payment.captured":
        return HttpResponse(status=200)

    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = payment_entity.get("order_id", "")
    payment_id = payment_entity.get("id", "")

    payment_order = PaymentOrder.objects.filter(
        razorpay_order_id=order_id,
        status=PaymentOrder.Status.CREATED,
    ).first()
    if payment_order:
        activate_after_payment(payment_order, payment_id)
    return HttpResponse(status=200)
