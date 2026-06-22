from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Customer, Users, Lead, LeadActivity


@admin.register(Users)
class UsersAdmin(BaseUserAdmin):
    model = Users

    list_display = (
        "u_id",
        "username",
        "email",
        "full_name",
        "phone",
        "role",
        "is_staff",
        "is_active",
    )
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "email", "full_name", "phone")
    ordering = ("username",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Profile", {"fields": ("full_name", "email", "phone", "role")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "full_name",
                    "email",
                    "phone",
                    "role",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("cust_id", "u_id", "aadhar_number")
    search_fields = (
        "u_id__username",
        "u_id__email",
        "u_id__full_name",
        "u_id__phone",
        "aadhar_number",
    )


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("lead_id", "full_name", "phone", "status", "p_id", "assigned_to", "created_at")
    list_filter = ("status", "source")
    search_fields = ("full_name", "phone", "email")


@admin.register(LeadActivity)
class LeadActivityAdmin(admin.ModelAdmin):
    list_display = ("activity_id", "lead", "activity_type", "created_by", "created_at")
