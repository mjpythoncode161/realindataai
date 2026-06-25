from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum


class LedgerMaster(models.Model):
    GROUP_CHOICES = [
        ("BANK_CASH", "Bank / Cash"),
        ("ASSET", "Asset"),
        ("LIABILITY", "Liability"),
        ("INCOME", "Income"),
        ("EXPENSE", "Expense"),
        ("CAPITAL", "Capital"),
        ("STAFF", "Staff Member"),
    ]
    DR_CR = [("Dr", "Debit"), ("Cr", "Credit")]

    l_id = models.AutoField(primary_key=True)
    organization = models.ForeignKey(
        "saas.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tally_ledgers",
    )
    name = models.CharField(max_length=200)
    group = models.CharField(max_length=20, choices=GROUP_CHOICES)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    opening_balance_type = models.CharField(max_length=2, choices=DR_CR, default="Dr")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name

    def current_balance(self) -> Decimal:
        total_dr = self.entries.aggregate(t=Sum("dr_amount"))["t"] or Decimal("0.00")
        total_cr = self.entries.aggregate(t=Sum("cr_amount"))["t"] or Decimal("0.00")
        if self.opening_balance_type == "Dr":
            return self.opening_balance + total_dr - total_cr
        return self.opening_balance + total_cr - total_dr

    def current_balance_type(self) -> str:
        bal = self.current_balance()
        if self.opening_balance_type == "Dr":
            return "Dr" if bal >= 0 else "Cr"
        return "Cr" if bal >= 0 else "Dr"

    class Meta:
        db_table = "tally_ledger_master"
        ordering = ["name"]
        unique_together = ("organization", "name")


class Voucher(models.Model):
    TYPE_CHOICES = [
        ("PAYMENT", "Payment Voucher"),
        ("RECEIPT", "Receipt Voucher"),
        ("JOURNAL", "Journal Entry"),
        ("CONTRA", "Contra"),
    ]

    v_id = models.AutoField(primary_key=True)
    organization = models.ForeignKey(
        "saas.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tally_vouchers",
    )
    voucher_no = models.CharField(max_length=50, blank=True)
    voucher_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    voucher_date = models.DateField()
    narration = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="tally_vouchers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.voucher_no} ({self.get_voucher_type_display()})"

    @property
    def total_dr(self) -> Decimal:
        return self.entries.aggregate(t=Sum("dr_amount"))["t"] or Decimal("0.00")

    @property
    def total_cr(self) -> Decimal:
        return self.entries.aggregate(t=Sum("cr_amount"))["t"] or Decimal("0.00")

    def save(self, *args, **kwargs):
        if not self.voucher_no:
            from datetime import date as _date
            date_str = (self.voucher_date or _date.today()).strftime("%Y%m%d")
            prefix = {"PAYMENT": "PV", "RECEIPT": "RV", "JOURNAL": "JV", "CONTRA": "CV"}.get(
                self.voucher_type, "VV"
            )
            last_qs = Voucher.objects.filter(voucher_type=self.voucher_type)
            if self.organization_id:
                last_qs = last_qs.filter(organization_id=self.organization_id)
            last = last_qs.order_by("-v_id").first()
            seq = (last.v_id + 1) if last else 1
            self.voucher_no = f"{prefix}-{date_str}-{seq:04d}"
        super().save(*args, **kwargs)

    class Meta:
        db_table = "tally_voucher"
        ordering = ["-voucher_date", "-v_id"]
        unique_together = ("organization", "voucher_no")


class VoucherEntry(models.Model):
    ve_id = models.AutoField(primary_key=True)
    v_id = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name="entries", db_column="v_id")
    ledger = models.ForeignKey(
        LedgerMaster, on_delete=models.PROTECT, related_name="entries", db_column="l_id"
    )
    dr_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    cr_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    narration = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return f"{self.ledger.name}  Dr:{self.dr_amount}  Cr:{self.cr_amount}"

    class Meta:
        db_table = "tally_voucher_entry"
