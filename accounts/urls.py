from django.urls import path
from . import views
from . import lead_views


urlpatterns = [
    path("", views.landing_home, name="landing_home"),
    path("signup/", views.public_signup, name="public_signup"),
    path("trial-expired/", views.trial_expired, name="trial_expired"),
    path("pending-approval/", views.pending_approval, name="pending_approval"),
    path(
        "followup/signup-approvals/",
        views.followup_signup_approvals,
        name="followup_signup_approvals",
    ),
    path("login/", views.login_view, name="login"),
    path("home/", views.home, name="home"),
    path("logout/", views.logout_view, name="logout"),
    path("account/profile/", views.manage_account, name="manage_account"),
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/add/", views.register_customer, name="register_customer"),
    path("customers/<int:cust_id>/edit/", views.edit_customer, name="edit_customer"),
    path("leads/", lead_views.lead_list, name="lead_list"),
    path("leads/add/", lead_views.lead_add, name="lead_add"),
    path("leads/check-booking/", lead_views.lead_check_booking, name="lead_check_booking"),
    path("leads/<int:lead_id>/", lead_views.lead_detail, name="lead_detail"),
    path("leads/<int:lead_id>/edit/", lead_views.lead_edit, name="lead_edit"),
    path("leads/<int:lead_id>/confirm/", lead_views.lead_confirm, name="lead_confirm"),
    path("leads/<int:lead_id>/close/", lead_views.lead_close_lost, name="lead_close_lost"),
    path("leads/activity/<int:activity_id>/edit/", lead_views.activity_edit, name="activity_edit"),
    path("leads/activity/<int:activity_id>/delete/", lead_views.activity_delete, name="activity_delete"),
    path("users/", views.user_list, name="user_list"),
    path("users/add/", views.add_user, name="add_user"),
    path("users/add/", views.add_user, name="user_add"),
    path("users/<int:user_id>/edit/", views.edit_user, name="edit_user"),
    path("users/<int:user_id>/edit/", views.edit_user, name="user_edit"),
    path("users/<int:user_id>/assign-role/", views.assign_user_role, name="assign_user_role"),
    path("users/<int:user_id>/delete/", views.delete_user, name="delete_user"),
    path("users/<int:user_id>/delete/", views.delete_user, name="user_delete"),
    path("activity-log/", views.activity_log, name="activity_log"),
]
