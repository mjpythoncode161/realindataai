from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.login_api, name="login_api"),
    path("me/", views.me_api, name="me_api"),
    path("logout/", views.logout_api, name="logout_api"),
    path("bookings/", views.bookings_list_api, name="bookings_list_api"),
    path("payments/", views.payments_list_api, name="payments_list_api"),
    path("users/", views.users_list_api, name="users_list_api"),
    path("users/<int:user_id>/", views.user_profile_api, name="user_profile_api"),
]