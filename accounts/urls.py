from django.urls import path
from . import views

app_name = 'accounts'
urlpatterns = [
    # Registration
    path('register/', views.register_view, name='register'),
    path("verify/", views.verify_registration, name="verify_registration"),
    path("verify/resend/", views.resend_code, name="resend_code"),
    path("register/cancel/", views.cancel_registration, name="cancel_registration"),

    # Login / Logout
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # Google OAuth
    path("google/", views.google_oauth_view, name="google_oauth"),
    path("google/callback/", views.google_callback_view, name="google_callback"),
    path("google/username/", views.google_username_view, name="google_username"),

    # Profile
    path("profile/", views.profile_settings, name="profile"),

    # Email change
    path("email/change/", views.profile_settings, name="request_email_change"),
    path("email/verify/", views.verify_email_change, name="verify_email_change"),
    path("email/resend/", views.resend_verification_code_profile, name="resend_email_change_code"),

    # Security
    path("password/change/", views.password_change_view, name="change_password"),
    path("password/set/",      views.set_password_view,      name="set_password"),
    path("google/disconnect/", views.disconnect_google_view, name="disconnect_google"),
    path("account/delete/",  views.delete_account_view, name="delete_account"),

    # Password reset (Django built-in flow)
    path("password/reset/",
         views.PlanforgePasswordResetView.as_view(), name="password_reset"),
    path("password/reset/sent/",
         views.PlanforgePasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/",
         views.PlanforgePasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/reset/complete/",
         views.PlanforgePasswordResetCompleteView.as_view(), name="password_reset_complete"),
]