from django.contrib import admin

from .models import (
    AccountsDebitPayment,
    AgentMaster,
    BalanceMaster,
    BookingAgentSettings,
    BookingItem,
    BookingMaster,
    CancelledPlot,
    IncentiveWithdrawalRequest,
    Payment,
    Project,
    ReceiptMaster,
)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("p_id", "name", "location")
    search_fields = ("name", "location")


@admin.register(AgentMaster)
class AgentMasterAdmin(admin.ModelAdmin):
    list_display = ("am_id", "u_id", "role", "commission_percentage", "tds_amount", "security_amount")
    list_filter = ("role",)
    search_fields = ("u_id__full_name", "u_id__email")


class BookingItemInline(admin.TabularInline):
    model = BookingItem
    extra = 0


@admin.register(BookingMaster)
class BookingMasterAdmin(admin.ModelAdmin):
    list_display = ("b_id", "booking_date", "full_name", "phone", "p_id")
    list_filter = ("booking_date", "p_id")
    search_fields = ("full_name", "phone", "email")
    inlines = [BookingItemInline]


@admin.register(BalanceMaster)
class BalanceMasterAdmin(admin.ModelAdmin):
    list_display = ("b_id", "total_amount", "paid_amount", "balance_amount")
    search_fields = ("b_id__full_name", "b_id__phone")


@admin.register(IncentiveWithdrawalRequest)
class IncentiveWithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = (
        "iwr_id",
        "requested_by",
        "role",
        "amount",
        "status",
        "requested_at",
        "processed_by",
        "processed_at",
    )
    list_filter = ("status", "role")
    search_fields = ("requested_by__full_name", "requested_by__email", "remarks")


@admin.register(ReceiptMaster)
class ReceiptMasterAdmin(admin.ModelAdmin):
    list_display = ("receipt_no", "receipt_date", "customer_name", "phone", "pay_amount", "balance_amount", "payment_method")
    list_filter = ("payment_method", "receipt_date")
    search_fields = ("receipt_no", "customer_name", "phone")
    ordering = ("-receipt_date",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("p_id", "b_id", "pay_amount", "payment_date", "payment_method", "status", "created_by", "created_at")
    list_filter = ("status", "payment_method")
    search_fields = ("b_id__full_name", "b_id__phone")
    ordering = ("-created_at",)


@admin.register(CancelledPlot)
class CancelledPlotAdmin(admin.ModelAdmin):
    list_display = ("cp_id", "b_id", "cancellation_date", "plot_number", "paid_amount", "refund_status", "closure_status", "released_for_rebooking")
    list_filter = ("refund_status", "closure_status", "released_for_rebooking")
    search_fields = ("b_id__full_name", "b_id__phone", "plot_number")


@admin.register(BookingAgentSettings)
class BookingAgentSettingsAdmin(admin.ModelAdmin):
    list_display = ("settings_id", "company_name", "enable_manager", "enable_executive", "enable_telecaller")


@admin.register(AccountsDebitPayment)
class AccountsDebitPaymentAdmin(admin.ModelAdmin):
    list_display = ("adp_id", "agent_master", "debit_type", "amount", "payment_date", "payment_method", "created_at")
    list_filter = ("debit_type", "payment_method")
    search_fields = ("agent_master__u_id__full_name", "remarks")
    ordering = ("-payment_date",)


@admin.register(BookingItem)
class BookingItemAdmin(admin.ModelAdmin):
    list_display = ("bi_id", "b_id", "p_id", "plot_number", "area_sqft", "rate", "booking_amount", "total_amount")
    search_fields = ("plot_number", "plot_name", "b_id__full_name")
