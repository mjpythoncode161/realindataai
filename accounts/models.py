from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.utils import timezone


ROLE_PRIORITY = (
    "admin",
    "accounts",
    "manager",
    "executive",
    "telecaller",
    "followup",
    "customer",
)


def users_with_role_query(role_name):
    return Q(role=role_name) | Q(roles__icontains=role_name)


def users_with_any_role_query(*role_names):
    query = Q()
    for role_name in role_names:
        query |= users_with_role_query(role_name)
    return query


class Customer(models.Model):
    cust_id = models.AutoField(primary_key=True)
    u_id = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='u_id')
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=15, blank=True)
    email = models.EmailField(max_length=255, blank=True)
    aadhar_number = models.CharField(max_length=12, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    occupation = models.CharField(max_length=200, blank=True, default="")
    present_address = models.TextField(blank=True, default="")
    permanent_address = models.TextField(blank=True, default="")
    pin_code = models.CharField(max_length=10, blank=True, default="")
    nominee = models.CharField(max_length=200, blank=True, default="")
    relationship = models.CharField(max_length=100, blank=True, default="")

    def save(self, *args, **kwargs):
        if self.u_id:
            self.full_name = self.u_id.full_name
            self.phone = self.u_id.phone
            self.email = self.u_id.email
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name or (self.u_id.full_name if self.u_id else "")

    class Meta:
        db_table = "customers"


class Users(AbstractUser):
    u_id = models.AutoField(primary_key=True)
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("customer", "Customer"),
        ("manager", "Manager"),
        ("executive", "Executive"),
        ("telecaller", "Telecaller"),
        ("accounts", "Accounts"),
        ("followup", "Followup"),
    ]
    full_name = models.CharField(max_length=150)
    email = models.EmailField(max_length=255, unique=True)
    phone = models.CharField(max_length=15, unique=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="customer")
    roles = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_users")
    company_name = models.CharField(max_length=200, blank=True, default="")
    organization = models.ForeignKey(
        "saas.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )
    is_trial_account = models.BooleanField(default=False)
    trial_started_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    signup_approved = models.BooleanField(default=True)
    signup_approved_at = models.DateTimeField(null=True, blank=True)
    signup_approved_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="signup_approvals_given",
    )

    def __str__(self):
        return self.full_name or self.username

    REQUIRED_FIELDS = ["email", "full_name", "phone"]

    @property
    def name(self) -> str:
        return self.full_name

    @property
    def contact(self) -> str:
        return self.phone

    @property
    def type(self) -> int:
        role_to_type = {
            "admin": 1,
            "customer": 2,
            "executive": 3,
            "manager": 4,
            "telecaller": 5,
            "accounts": 6,
            "followup": 7,
        }
        return role_to_type.get(self.role, 2)

    def get_roles(self):
        if getattr(self, 'is_superuser', False):
            return ["admin"]
        if self.roles:
            stored = [r for r in self.roles if r in dict(self.ROLE_CHOICES)]
            if stored:
                roles = stored
            elif self.role:
                roles = [self.role]
            else:
                roles = ["customer"]
        elif self.role:
            roles = [self.role]
        else:
            roles = ["customer"]
        if self.role in dict(self.ROLE_CHOICES) and self.role not in roles:
            roles = list(roles) + [self.role]
        if self.is_paid_org_owner() and "admin" not in roles:
            return ["admin"] + [r for r in roles if r != "admin"]
        return roles

    def is_paid_org_owner(self):
        """Org owner with active subscription gets full admin CRM access on any plan."""
        org = getattr(self, "organization", None)
        if org is None:
            try:
                from saas.models import Organization

                org = Organization.objects.filter(owner_id=self.u_id).first()
            except Exception:
                return False
        if not org or not org.is_subscription_active:
            return False
        return org.owner_id == self.u_id

    def has_role(self, role_name):
        return role_name in self.get_roles()

    def has_any_role(self, *role_names):
        user_roles = set(self.get_roles())
        return bool(user_roles.intersection(role_names))

    def is_lead_only_staff(self):
        """Executive or telecaller without admin, manager, or accounts access."""
        roles = set(self.get_roles())
        if roles.intersection({"admin", "manager", "accounts"}):
            return False
        return bool(roles.intersection({"executive", "telecaller"}))

    def is_manager_only_staff(self):
        """Manager without admin or accounts access."""
        if self.has_any_role("admin", "accounts"):
            return False
        return self.has_role("manager")

    def is_accounts_only_staff(self):
        """Accounts role without admin access."""
        if self.has_role("admin"):
            return False
        return self.has_role("accounts")

    def can_manage_bookings(self):
        """True for staff who may add/edit/cancel bookings (uses get_roles(), not the role DB field)."""
        return self.has_any_role("admin", "manager", "executive", "telecaller")

    def set_roles(self, role_list):
        valid = []
        for role_name in role_list or []:
            if role_name in dict(self.ROLE_CHOICES) and role_name not in valid:
                valid.append(role_name)
        if not valid:
            valid = ["customer"]
        self.roles = valid
        self.role = self._primary_role(valid)

    @staticmethod
    def _primary_role(role_list):
        for role_name in ROLE_PRIORITY:
            if role_name in role_list:
                return role_name
        return role_list[0]

    def get_roles_display(self):
        labels = dict(self.ROLE_CHOICES)
        return ", ".join(labels.get(role_name, role_name) for role_name in self.get_roles())

    @classmethod
    def filter_by_role(cls, role_name):
        return cls.objects.filter(users_with_role_query(role_name))

    @property
    def cust_id(self):
        try:
            return self.customer.cust_id
        except:
            return None

    @property
    def pending_signup_approval(self):
        return self.is_trial_account and not self.signup_approved

    @property
    def can_access_dashboard(self):
        if self.pending_signup_approval:
            return False
        return True

    @property
    def trial_is_active(self):
        if not self.is_trial_account:
            return True
        if not self.signup_approved:
            return False
        if not self.trial_ends_at:
            return False
        return timezone.now() <= self.trial_ends_at

    @property
    def trial_days_remaining(self):
        if not self.is_trial_account or not self.trial_ends_at:
            return 0
        delta = self.trial_ends_at - timezone.now()
        return max(0, delta.days + (1 if delta.seconds > 0 else 0))

    def start_trial(self, days=7):
        now = timezone.now()
        self.is_trial_account = True
        self.trial_started_at = now
        self.trial_ends_at = now + timedelta(days=days)
        self.save(update_fields=["is_trial_account", "trial_started_at", "trial_ends_at"])

    class Meta:
        db_table = "users"


class Lead(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        CONTACTED = "CONTACTED", "Contacted"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CLOSED_LOST = "CLOSED_LOST", "Closed (Lost)"

    class Source(models.TextChoices):
        CALL = "CALL", "Phone Call"
        WALK_IN = "WALK_IN", "Walk-in"
        WEBSITE = "WEBSITE", "Website"
        REFERRAL = "REFERRAL", "Referral"
        SOCIAL = "SOCIAL", "Social Media"
        OTHER = "OTHER", "Other"

    lead_id = models.AutoField(primary_key=True)
    organization = models.ForeignKey(
        "saas.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="leads",
    )
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=15)
    email = models.EmailField(max_length=255, blank=True, default="")
    p_id = models.ForeignKey(
        "bookings.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )
    plot_interest = models.CharField(max_length=200, blank=True, default="")
    budget = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.CALL)
    occupation = models.CharField(max_length=200, blank=True, default="")
    present_address = models.TextField(blank=True, default="")
    aadhar_number = models.CharField(max_length=12, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    next_follow_up_date = models.DateField(null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_leads",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="leads_created",
    )
    converted_customer = models.OneToOneField(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_lead",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leads"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.full_name} ({self.phone})"

    @property
    def is_open(self):
        return self.status not in (self.Status.CONFIRMED, self.Status.CLOSED_LOST)


class LeadActivity(models.Model):
    class ActivityType(models.TextChoices):
        CALL = "CALL", "Phone Call"
        VISIT = "VISIT", "Site Visit"
        NOTE = "NOTE", "Note"
        STATUS = "STATUS", "Status Update"

    activity_id = models.AutoField(primary_key=True)
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=20, choices=ActivityType.choices, default=ActivityType.NOTE)
    note = models.TextField()
    next_follow_up_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="lead_activities",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "lead_activities"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.lead.full_name} — {self.get_activity_type_display()}"


class ActivityLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Created"
        EDIT   = "EDIT",   "Edited"
        DELETE = "DELETE",  "Deleted"
        CANCEL = "CANCEL",  "Cancelled"
        APPROVE = "APPROVE", "Approved"
        STATUS = "STATUS",  "Status Changed"

    organization = models.ForeignKey(
        "saas.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="activity_logs",
    )
    action      = models.CharField(max_length=20, choices=Action.choices)
    model_name  = models.CharField(max_length=60)
    object_id   = models.CharField(max_length=60, blank=True, default="")
    object_repr = models.CharField(max_length=255, blank=True, default="")
    changes     = models.TextField(blank=True, default="")
    timestamp   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "activity_log"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.user} — {self.action} {self.model_name} #{self.object_id}"
