from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.conf import settings


class Project(models.Model):
    p_id = models.AutoField(primary_key=True)
    organization = models.ForeignKey(
        "saas.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="projects",
    )
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    num_plots = models.IntegerField(default=0)

    def __str__(self) -> str:
        return self.name

    class Meta:
        db_table = "project"
        unique_together = ("organization", "name")


class AgentMaster(models.Model):
    am_id = models.AutoField(primary_key=True)
    class Role(models.TextChoices):
        MANAGER = "manager", "Manager"
        EXECUTIVE = "executive", "Executive"
        TELECALLER = "telecaller", "Telecaller"
        ACCOUNTS = "accounts", "Accounts"

    u_id = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_column='u_id', related_name="agent_profiles")
    role = models.CharField(max_length=20, choices=Role.choices)
    commission_percentage = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0.0000"))
    tds_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    security_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    effective_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(
        max_length=20,
        choices=[
            ("CASH", "Cash"),
            ("BANK_TRANSFER", "Bank Transfer"),
            ("UPI", "UPI"),
            ("CHEQUE", "Cheque"),
        ],
        blank=True,
        default="",
    )
    remarks = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return f"{self.u_id.full_name} ({self.get_role_display()})"

    class Meta:
        db_table = "agent_master"
        unique_together = ("u_id", "role")


class AccountsDebitPayment(models.Model):
    """Multiple commission / security debit payments per agent (accounts profile)."""

    class DebitType(models.TextChoices):
        COMMISSION = "COMMISSION", "Commission (Debit)"
        SECURITY = "SECURITY", "Security Deposit (Debit)"

    PAYMENT_METHOD_CHOICES = [
        ("CASH", "Cash"),
        ("BANK_TRANSFER", "Bank Transfer"),
        ("UPI", "UPI"),
        ("CHEQUE", "Cheque"),
    ]

    adp_id = models.AutoField(primary_key=True)
    agent_master = models.ForeignKey(
        AgentMaster,
        on_delete=models.CASCADE,
        related_name="debit_payments",
        limit_choices_to={"role": AgentMaster.Role.ACCOUNTS},
    )
    debit_type = models.CharField(max_length=20, choices=DebitType.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    payment_date = models.DateField()
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default="CASH")
    remarks = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_debit_payment"
        ordering = ["payment_date", "adp_id"]

    def __str__(self) -> str:
        return f"{self.get_debit_type_display()} ₹{self.amount} ({self.payment_date})"


class BookingMaster(models.Model):
    b_id = models.AutoField(primary_key=True)
    organization = models.ForeignKey(
        "saas.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bookings",
    )
    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"
        UPI = "UPI", "UPI"
        CHEQUE = "CHEQUE", "Cheque"

    class PaymentStatus(models.TextChoices):
        FULL = "FULL", "Full Payment"
        PARTIAL = "PARTIAL", "Partial Payment"

    class BookingStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CANCELLED = "CANCELLED", "Cancelled"

    booking_date = models.DateField()

    phone = models.CharField(max_length=15)
    full_name = models.CharField(max_length=200)
    email = models.EmailField(max_length=255, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    occupation = models.CharField(max_length=200, blank=True)
    present_address = models.TextField(blank=True)
    permanent_address = models.TextField(blank=True)
    aadhar_number = models.CharField(max_length=12, blank=True)
    pin_code = models.CharField(max_length=10, blank=True)

    u_id = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='u_id',
        related_name="customer_bookings"
    )

    @property
    def customer_full_name(self):
        """Returns the linked user's name or the snapshot name."""
        return self.u_id.full_name if self.u_id else self.full_name

    @property
    def customer_phone(self):
        """Returns the linked user's phone or the snapshot phone."""
        return self.u_id.phone if self.u_id else self.phone

    @property
    def customer_email(self):
        """Returns the linked user's email or the snapshot email."""
        return self.u_id.email if self.u_id else self.email

    @property
    def customer_aadhar(self):
        """Fetches Aadhaar from the linked Customer profile if available."""
        if self.u_id and hasattr(self.u_id, 'customer'):
            return self.u_id.customer.aadhar_number
        return self.aadhar_number

    @property
    def project_location(self):
        """Fetches location from the linked Project."""
        return self.p_id.location if self.p_id else self.location

    manager_u_id = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='manager_u_id',
        related_name="managed_bookings",
        limit_choices_to={"role": "manager"},
    )
    manager_percentage = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal("0.0000"))
    manager_tds = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    manager_security_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    executive_u_id = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='executive_u_id',
        related_name="executive_bookings",
        limit_choices_to={"role": "executive"},
    )
    executive_percentage = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal("0.0000"))
    executive_tds = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    executive_security_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    telecaller_u_id = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='telecaller_u_id',
        related_name="telecaller_bookings",
        limit_choices_to={"role": "telecaller"},
    )
    telecaller_percentage = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal("0.0000"))
    telecaller_tds = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    telecaller_security_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    payment_status = models.CharField(
        max_length=10,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PARTIAL,
    )
    status = models.CharField(
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.ACTIVE,
    )
    payment_details = models.TextField(blank=True)

    nominee = models.CharField(max_length=200, blank=True)
    relationship = models.CharField(max_length=100, blank=True)

    p_id = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, db_column='p_id', related_name="bookings")
    location = models.CharField(max_length=200, blank=True)
    next_payment_date = models.DateField(null=True, blank=True)

    kgp_completed = models.BooleanField(
        default=False,
        help_text="Government survey (KGP) completed for this booking.",
    )
    kgp_completed_at = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_bookings"
    )

    @property
    def booking_no(self) -> str:
        date_str = self.booking_date.strftime("%Y%m%d") if self.booking_date else "00000000"
        return f"BK{date_str}-{self.b_id:04d}"

    def __str__(self) -> str:
        return f"{self.booking_no} - {self.full_name}"

    def save(self, *args, **kwargs):
        # Rule: Baseline follow-up is always booking_date + 30 days
        if self.booking_date:
            from datetime import timedelta
            self.next_payment_date = self.booking_date + timedelta(days=30)
        super().save(*args, **kwargs)

    class Meta:
        db_table = "booking_master"


class BookingItem(models.Model):
    bi_id = models.AutoField(primary_key=True)
    b_id = models.ForeignKey(BookingMaster, on_delete=models.CASCADE, db_column='b_id', related_name="items")

    p_id = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, db_column='p_id', related_name="booking_items")
    plot_number = models.CharField(max_length=50, blank=True)
    plot_name = models.CharField(max_length=200, blank=True)

    area_sqft = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    rate = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    booking_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    def save(self, *args, **kwargs):
        self.total_amount = (self.area_sqft or Decimal("0.00")) * (self.rate or Decimal("0.00"))
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Item for Booking {self.b_id_id}"

    class Meta:
        db_table = "booking_item"


class BalanceMaster(models.Model):
    bm_id = models.AutoField(primary_key=True)
    b_id = models.OneToOneField(BookingMaster, on_delete=models.CASCADE, db_column='b_id', related_name="balance")

    plot_number = models.CharField(max_length=50, blank=True)
    plot_name = models.CharField(max_length=200, blank=True)
    project_name = models.CharField(max_length=200, blank=True)

    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    balance_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    booking_advance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    @property
    def display_project_name(self):
        """Fetches the latest project name from the linked booking."""
        return self.b_id.p_id.name if self.b_id and self.b_id.p_id else self.project_name

    @property
    def display_plot_number(self):
        """Fetches the latest plot numbers from the linked booking."""
        if self.b_id:
            return ", ".join([it.plot_number for it in self.b_id.items.all() if it.plot_number])
        return self.plot_number

    def recalculate(self) -> None:
        """
        Recalculates total, paid, and balance based on booking items and receipts.
        Initial paid amount comes from the booking_amount in BookingItem.
        Subsequent payments come from ReceiptMaster.
        """
        if not self.b_id:
            return

        items = self.b_id.items.all()
        # 1. Total Property Value (Sum of Area * Rate for all items)
        total = sum((it.area_sqft * it.rate for it in items), Decimal("0.00"))
        
        # 2. Initial Payment (Sum of booking_amount from all items)
        initial_paid = sum((it.booking_amount for it in items), Decimal("0.00"))
        
        # 3. Subsequent Payments (Sum of pay_amount from all receipts)
        receipt_paid = sum((r.pay_amount for r in self.b_id.receipts.all()), Decimal("0.00"))
        
        self.total_amount = total
        self.booking_advance = initial_paid
        self.paid_amount = initial_paid + receipt_paid
        self.balance_amount = self.total_amount - self.paid_amount
        
        # Update payment_status on BookingMaster
        if self.balance_amount <= 0:
            self.b_id.payment_status = "FULL"
        else:
            self.b_id.payment_status = "PARTIAL"
        self.b_id.save()

        # Sync plot details for snapshotting
        self.plot_number = ", ".join(filter(None, [it.plot_number for it in items]))
        self.plot_name = self.b_id.p_id.name if self.b_id.p_id else ""
        self.project_name = self.plot_name

    def save(self, *args, **kwargs):
        self.balance_amount = (self.total_amount or Decimal("0.00")) - (
            self.paid_amount or Decimal("0.00")
        )
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Balance for {self.b_id.booking_no}"

    class Meta:
        db_table = "balance_master"


class ReceiptMaster(models.Model):
    rm_id = models.AutoField(primary_key=True)
    receipt_date = models.DateField()
    receipt_no = models.CharField(max_length=50, unique=True, blank=True)
    b_id = models.ForeignKey(
        BookingMaster,
        on_delete=models.CASCADE,
        db_column="b_id",
        related_name="receipts",
    )
    # Snapshots of data at time of receipt
    customer_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=15)
    plot_number = models.CharField(max_length=200)
    total_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    pay_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    balance_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    payment_method = models.CharField(
        max_length=20,
        choices=BookingMaster.PaymentMethod.choices,
        default=BookingMaster.PaymentMethod.CASH,
    )
    payment_details = models.TextField(blank=True)
    next_payment_date = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.receipt_no:
            # Auto-generate receipt number: RCPT-YYYYMMDD-XXXX
            date_str = self.receipt_date.strftime("%Y%m%d") if self.receipt_date else "00000000"
            last_receipt = ReceiptMaster.objects.filter(receipt_no__contains=date_str).order_by("-rm_id").first()
            if last_receipt:
                try:
                    last_id = int(last_receipt.receipt_no.split("-")[-1])
                    new_id = last_id + 1
                except:
                    new_id = 1
            else:
                new_id = 1
            self.receipt_no = f"RCPT-{date_str}-{new_id:04d}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.receipt_no} - {self.customer_name}"

    class Meta:
        db_table = "receipt_master"
        ordering = ["-created_at"]


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    p_id = models.AutoField(primary_key=True)
    b_id = models.ForeignKey(BookingMaster, on_delete=models.CASCADE, related_name="pending_payments")
    pay_amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField()
    next_payment_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=20, choices=BookingMaster.PaymentMethod.choices)
    payment_details = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Payment {self.p_id} - {self.status}"

    class Meta:
        db_table = "payments"


class IncentiveWithdrawalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    iwr_id = models.AutoField(primary_key=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_column="requested_by",
        related_name="incentive_withdrawal_requests",
    )
    role = models.CharField(max_length=20, choices=AgentMaster.Role.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="processed_by",
        related_name="processed_incentive_withdrawals",
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    proof_image = models.ImageField(upload_to="withdrawal_proofs/", null=True, blank=True)
    remarks = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.requested_by.full_name} - {self.amount} - {self.status}"

    class Meta:
        db_table = "incentive_withdrawal_request"
        ordering = ["-requested_at"]


class CancelledPlot(models.Model):
    class RefundStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PARTIAL = "PARTIAL", "Partial Refund"
        COMPLETED = "COMPLETED", "Completed"

    class ClosureStatus(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    cp_id = models.AutoField(primary_key=True)
    b_id = models.OneToOneField(BookingMaster, on_delete=models.CASCADE, related_name="cancelled_details")
    cancellation_date = models.DateField(auto_now_add=True)
    reason = models.TextField()
    plot_number = models.CharField(max_length=200, blank=True)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    refund_status = models.CharField(max_length=20, choices=RefundStatus.choices, default=RefundStatus.PENDING)
    closure_status = models.CharField(max_length=10, choices=ClosureStatus.choices, default=ClosureStatus.OPEN)
    released_for_rebooking = models.BooleanField(default=False)
    refund_amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    refund_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def __str__(self) -> str:
        return f"Cancelled Plot - {self.b_id.booking_no}"

    class Meta:
        db_table = "cancelled_plot"


class BookingAgentSettings(models.Model):
    """Per-organization company profile and agent role toggles."""

    settings_id = models.AutoField(primary_key=True)
    organization = models.OneToOneField(
        "saas.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="booking_settings",
    )
    company_name = models.CharField(max_length=200, default="LANDLINK REAL ESTATE", blank=True)
    company_address = models.TextField(blank=True, default="")
    company_phone = models.CharField(max_length=30, blank=True, default="")
    company_email = models.EmailField(blank=True, default="")
    enable_manager = models.BooleanField(default=True)
    enable_executive = models.BooleanField(default=True)
    enable_telecaller = models.BooleanField(default=True)

    class Meta:
        db_table = "booking_agent_settings"
        verbose_name = "Booking agent settings"
        verbose_name_plural = "Booking agent settings"

    def __str__(self) -> str:
        enabled = ", ".join(role.title() for role in self.enabled_roles()) or "None"
        return f"Booking agents: {enabled}"

    def is_role_enabled(self, role: str) -> bool:
        mapping = {
            "manager": self.enable_manager,
            "executive": self.enable_executive,
            "telecaller": self.enable_telecaller,
        }
        return mapping.get(role, False)

    def enabled_roles(self) -> list[str]:
        roles = []
        if self.enable_manager:
            roles.append("manager")
        if self.enable_executive:
            roles.append("executive")
        if self.enable_telecaller:
            roles.append("telecaller")
        return roles

    @property
    def show_team_report(self) -> bool:
        return len(self.enabled_roles()) >= 2


def get_booking_agent_settings(organization=None) -> BookingAgentSettings:
    if organization is not None:
        settings_obj, _ = BookingAgentSettings.objects.get_or_create(
            organization=organization,
            defaults={"company_name": organization.name},
        )
        return settings_obj
    legacy = BookingAgentSettings.objects.filter(organization__isnull=True).first()
    if legacy:
        return legacy
    return BookingAgentSettings.objects.create(company_name="LANDLINK REAL ESTATE")

