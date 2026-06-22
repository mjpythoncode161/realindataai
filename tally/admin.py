from django.contrib import admin
from .models import LedgerMaster, Voucher, VoucherEntry


@admin.register(LedgerMaster)
class LedgerMasterAdmin(admin.ModelAdmin):
    list_display = ("name", "group", "opening_balance", "opening_balance_type", "is_active")
    list_filter = ("group", "is_active")
    search_fields = ("name",)


class VoucherEntryInline(admin.TabularInline):
    model = VoucherEntry
    extra = 0


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ("voucher_no", "voucher_type", "voucher_date", "created_by", "created_at")
    list_filter = ("voucher_type",)
    search_fields = ("voucher_no", "narration")
    inlines = [VoucherEntryInline]
