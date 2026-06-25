import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class SubscriptionPlan(models.Model):
    """SaaS pricing tier: Basic, Premium, Diamond."""

    class Tier(models.TextChoices):
        BASIC = "basic", "Basic"
        PREMIUM = "premium", "Premium"
        DIAMOND = "diamond", "Diamond"

    plan_id = models.AutoField(primary_key=True)
    tier = models.CharField(max_length=20, choices=Tier.choices, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    price_inr = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    billing_period_days = models.PositiveIntegerField(default=30)
    max_projects = models.PositiveIntegerField(default=2, help_text="0 = unlimited")
    max_users = models.PositiveIntegerField(default=5, help_text="0 = unlimited")
    max_bookings = models.PositiveIntegerField(default=0, help_text="0 = unlimited")
    feature_leads = models.BooleanField(default=False)
    feature_reports = models.BooleanField(default=False)
    feature_agents = models.BooleanField(default=False)
    feature_tally = models.BooleanField(default=False)
    feature_api = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "saas_subscription_plan"
        ordering = ["sort_order", "price_inr"]

    def __str__(self):
        return f"{self.name} — ₹{self.price_inr}/mo"

    @property
    def is_unlimited_projects(self):
        return self.max_projects == 0

    @property
    def is_unlimited_users(self):
        return self.max_users == 0

    def feature_list(self):
        features = ["Bookings & customers", "Dashboard"]
        if self.max_projects:
            features.append(f"Up to {self.max_projects} projects")
        else:
            features.append("Unlimited projects")
        if self.max_users:
            features.append(f"Up to {self.max_users} team users")
        else:
            features.append("Unlimited team users")
        if self.feature_leads:
            features.append("Lead management")
        if self.feature_reports:
            features.append("Reports & analytics")
        if self.feature_agents:
            features.append("Agent commission")
        if self.feature_tally:
            features.append("Tally integration")
        if self.feature_api:
            features.append("API access")
        return features


class Organization(models.Model):
    """Tenant — each paying company gets an isolated workspace."""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending Payment"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"

    org_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_organizations",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="organizations",
        null=True,
        blank=True,
    )
    subscription_started_at = models.DateTimeField(null=True, blank=True)
    subscription_ends_at = models.DateTimeField(null=True, blank=True)
    razorpay_customer_id = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "saas_organization"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "org"
            candidate = base
            n = 1
            while Organization.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                n += 1
                candidate = f"{base}-{n}"
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def is_subscription_active(self):
        if self.status != self.Status.ACTIVE:
            return False
        if not self.subscription_ends_at:
            return True
        return timezone.now() <= self.subscription_ends_at

    @property
    def days_remaining(self):
        if not self.subscription_ends_at:
            return 0
        delta = self.subscription_ends_at - timezone.now()
        return max(0, delta.days + (1 if delta.seconds > 0 else 0))

    def activate_subscription(self, plan, period_days=None):
        now = timezone.now()
        days = period_days or plan.billing_period_days
        self.plan = plan
        self.status = self.Status.ACTIVE
        self.subscription_started_at = now
        self.subscription_ends_at = now + timedelta(days=days)
        self.save(
            update_fields=[
                "plan",
                "status",
                "subscription_started_at",
                "subscription_ends_at",
                "updated_at",
            ]
        )

    def has_feature(self, feature_name):
        # Paid & active organizations get full CRM access regardless of plan tier.
        if self.is_subscription_active:
            return True
        if not self.plan:
            return False
        return getattr(self.plan, f"feature_{feature_name}", False)


class OrganizationMembership(models.Model):
    """Links users to their tenant organization."""

    membership_id = models.AutoField(primary_key=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
    )
    is_owner = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "saas_organization_membership"
        unique_together = ("organization", "user")

    def __str__(self):
        return f"{self.user} @ {self.organization.name}"


class PaymentOrder(models.Model):
    """Tracks Razorpay (or demo) subscription payments."""

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    order_id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="payment_orders",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    amount_inr = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="INR")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    razorpay_order_id = models.CharField(max_length=100, blank=True, default="")
    razorpay_payment_id = models.CharField(max_length=100, blank=True, default="")
    razorpay_signature = models.CharField(max_length=255, blank=True, default="")
    is_demo = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "saas_payment_order"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order #{self.order_id} — {self.organization.name} ({self.status})"
