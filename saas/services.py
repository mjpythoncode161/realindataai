import hashlib
import hmac
import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from saas.models import Organization, OrganizationMembership, PaymentOrder, SubscriptionPlan

logger = logging.getLogger(__name__)


def seed_default_plans():
    """Create or update Basic, Premium, Diamond plans."""
    plans = [
        {
            "tier": SubscriptionPlan.Tier.BASIC,
            "name": "Basic",
            "description": "Essential CRM for small agencies starting out.",
            "price_inr": Decimal("999.00"),
            "max_projects": 2,
            "max_users": 5,
            "feature_leads": False,
            "feature_reports": False,
            "feature_agents": False,
            "feature_tally": False,
            "feature_api": False,
            "sort_order": 1,
        },
        {
            "tier": SubscriptionPlan.Tier.PREMIUM,
            "name": "Premium",
            "description": "Full lead & report suite for growing teams.",
            "price_inr": Decimal("2499.00"),
            "max_projects": 10,
            "max_users": 25,
            "feature_leads": True,
            "feature_reports": True,
            "feature_agents": True,
            "feature_tally": False,
            "feature_api": False,
            "sort_order": 2,
        },
        {
            "tier": SubscriptionPlan.Tier.DIAMOND,
            "name": "Diamond",
            "description": "Unlimited power — Tally, API & enterprise features.",
            "price_inr": Decimal("4999.00"),
            "max_projects": 0,
            "max_users": 0,
            "feature_leads": True,
            "feature_reports": True,
            "feature_agents": True,
            "feature_tally": True,
            "feature_api": True,
            "sort_order": 3,
        },
    ]
    for data in plans:
        SubscriptionPlan.objects.update_or_create(tier=data["tier"], defaults=data)


@transaction.atomic
def create_organization_for_signup(user, company_name, plan):
    """Create pending org after signup; activates after payment."""
    from bookings.models import BookingAgentSettings

    org = Organization.objects.create(
        name=company_name,
        owner=user,
        plan=plan,
        status=Organization.Status.PENDING_PAYMENT,
    )
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        is_owner=True,
    )
    BookingAgentSettings.objects.get_or_create(
        organization=org,
        defaults={"company_name": company_name},
    )
    user.organization = org
    user.company_name = company_name
    user.is_trial_account = False
    user.signup_approved = True
    user.save(update_fields=["organization", "company_name", "is_trial_account", "signup_approved"])
    return org


def promote_org_owner_to_admin(org):
    """Paid org owner gets admin role — full sidebar & CRM on any plan."""
    owner = org.owner
    if not owner.has_role("admin"):
        roles = owner.get_roles()
        if "admin" not in roles:
            roles = ["admin"] + [r for r in roles if r != "admin"]
        owner.set_roles(roles)
        owner.save(update_fields=["roles", "role"])
    if not owner.organization_id:
        owner.organization = org
        owner.save(update_fields=["organization"])


@transaction.atomic
def activate_after_payment(payment_order, razorpay_payment_id="", razorpay_signature=""):
    """Mark order paid and activate organization subscription."""
    if payment_order.status == PaymentOrder.Status.PAID:
        return payment_order.organization

    org = payment_order.organization
    plan = payment_order.plan
    now = timezone.now()

    payment_order.status = PaymentOrder.Status.PAID
    payment_order.razorpay_payment_id = razorpay_payment_id or payment_order.razorpay_payment_id
    payment_order.razorpay_signature = razorpay_signature or payment_order.razorpay_signature
    payment_order.paid_at = now
    payment_order.save()

    org.activate_subscription(plan)

    owner = org.owner
    owner.is_trial_account = False
    owner.signup_approved = True
    owner.is_active = True
    owner.organization = org
    owner.save(update_fields=["is_trial_account", "signup_approved", "is_active", "organization"])
    promote_org_owner_to_admin(org)

    logger.info("SaaS activated: org=%s plan=%s", org.slug, plan.tier)
    return org


def create_payment_order(org, plan):
    """Create Razorpay order (or demo order when SAAS_DEMO_MODE=True)."""
    amount_paise = int(plan.price_inr * 100)
    demo_mode = getattr(settings, "SAAS_DEMO_MODE", True)

    order = PaymentOrder.objects.create(
        organization=org,
        plan=plan,
        amount_inr=plan.price_inr,
        is_demo=demo_mode,
    )

    if demo_mode:
        order.razorpay_order_id = f"demo_{order.uuid}"
        order.save(update_fields=["razorpay_order_id"])
        return order, None

    key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
    key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        order.is_demo = True
        order.razorpay_order_id = f"demo_{order.uuid}"
        order.save(update_fields=["is_demo", "razorpay_order_id"])
        return order, None

    try:
        import razorpay

        client = razorpay.Client(auth=(key_id, key_secret))
        rzp_order = client.order.create(
            {
                "amount": amount_paise,
                "currency": "INR",
                "receipt": str(order.uuid),
                "notes": {
                    "org_id": str(org.org_id),
                    "plan": plan.tier,
                },
            }
        )
        order.razorpay_order_id = rzp_order["id"]
        order.save(update_fields=["razorpay_order_id"])
        return order, rzp_order
    except Exception as exc:
        logger.exception("Razorpay order creation failed: %s", exc)
        order.status = PaymentOrder.Status.FAILED
        order.save(update_fields=["status"])
        raise


def verify_razorpay_signature(order_id, payment_id, signature):
    key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
    if not key_secret:
        return False
    body = f"{order_id}|{payment_id}"
    expected = hmac.new(
        key_secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def get_active_plans():
    return SubscriptionPlan.objects.filter(is_active=True).order_by("sort_order")
