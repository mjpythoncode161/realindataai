from django.contrib import admin

from saas.models import Organization, OrganizationMembership, PaymentOrder, SubscriptionPlan


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "tier",
        "price_inr",
        "max_projects",
        "max_users",
        "is_active",
        "sort_order",
    )
    list_filter = ("tier", "is_active")
    ordering = ("sort_order",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "plan", "status", "subscription_ends_at", "created_at")
    list_filter = ("status", "plan")
    search_fields = ("name", "slug", "owner__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "is_owner", "joined_at")
    list_filter = ("is_owner",)


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = ("order_id", "organization", "plan", "amount_inr", "status", "is_demo", "paid_at")
    list_filter = ("status", "is_demo")
    readonly_fields = ("uuid", "created_at")
