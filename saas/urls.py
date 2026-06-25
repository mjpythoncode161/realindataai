from django.urls import path

from saas import views
from saas import platform_views

urlpatterns = [
    path("choose-plan/", views.choose_plan, name="saas_choose_plan"),
    path("checkout/", views.checkout, name="saas_checkout"),
    path("payment/verify/", views.payment_verify, name="saas_payment_verify"),
    path("payment/success/", views.payment_success, name="saas_payment_success"),
    path("payment/webhook/", views.payment_webhook, name="saas_payment_webhook"),
    path("subscription-expired/", views.subscription_expired, name="subscription_expired"),
    # Platform super admin
    path("platform/", platform_views.platform_dashboard, name="platform_dashboard"),
    path("platform/organizations/", platform_views.platform_organizations, name="platform_organizations"),
    path("platform/organizations/<int:org_id>/", platform_views.platform_organization_detail, name="platform_organization_detail"),
    path("platform/plans/", platform_views.platform_plans, name="platform_plans"),
    path("platform/payments/", platform_views.platform_payments, name="platform_payments"),
    path("platform/users/", platform_views.platform_users, name="platform_users"),
]
