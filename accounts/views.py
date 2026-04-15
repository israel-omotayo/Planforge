import json
import logging
from django.template.loader import render_to_string
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST, require_http_methods
from django.urls import reverse_lazy
from django.conf import settings
from django.core.cache import cache
from core.utils import send_email, send_email_async, is_json_request
from core.ratelimit import check_ratelimit, RateLimitError
from .forms import SignUpForm, ProfileUpdateForm, LoginForm, VerifyCodeForm
from .models import UserProfile
from . import services, schemas

#creates a logger for this module to log important events and errors
logger = logging.getLogger(__name__)

# Get the User model
User = get_user_model()


# HELPER FUNCTIONS
#This gets the user’s IP address for rate limiting.
def get_ip(request):
    """
    Extract the user's real IP address for rate limiting.

    Two modes, selected automatically based on settings:

    1. Behind a trusted reverse proxy (Nginx, Cloudflare, AWS ALB):
       Set SECURE_PROXY_SSL_HEADER in prod.py and configure NUM_PROXIES.
       We then read X-Forwarded-For, skipping the rightmost NUM_PROXIES
       addresses (which belong to the proxy chain itself).

    2. Direct connection (default / dev):
       REMOTE_ADDR is used directly — it is set by the OS network stack
       and cannot be spoofed at the TCP level.

    NEVER enable proxy mode unless your proxy actively strips/overwrites
    X-Forwarded-For before it reaches Django. Otherwise any client can
    spoof the header and bypass rate limits entirely.
    """
    #Detect if we're behind a proxy by checking for the SECURE_PROXY_SSL_HEADER setting.
    behind_proxy = bool(getattr(settings, "SECURE_PROXY_SSL_HEADER", None))

    if behind_proxy:
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded_for:
            # X-Forwarded-For: client, proxy1, proxy2
            # We trust the proxy to have appended its own address last.
            # Strip the rightmost NUM_PROXIES entries (the proxy hops we own).
            num_proxies = getattr(settings, "NUM_PROXIES", 1)
            ips = [ip.strip() for ip in forwarded_for.split(",")]
            client_ips = ips[:-num_proxies] if len(ips) > num_proxies else ips
            return client_ips[-1] if client_ips else request.META.get("REMOTE_ADDR", "")

    return request.META.get("REMOTE_ADDR", "")

def json_response(status='success', message=None, data=None, code=None, http_status=200):
    """Standardized JSON response for API endpoints."""
    response = {'status': status}
    if message:
        response['message'] = message
    if data:
        response['data'] = data
    if code:
        response['code'] = code
    return JsonResponse(response, status=http_status)

def get_request_data(request):
    """Extract data from POST or JSON body."""
    if request.POST:
        return request.POST
    if request.body:
        try:
            return json.loads(request.body)
        except json.JSONDecodeError:
            return None
    return {}


def check_cooldown(cache_key, duration=60):
    """Check if action is in cooldown period. Returns True if should block."""
    # If the key exists in cache, it means the cooldown is active.
    return cache.get(cache_key) is not None


def set_cooldown(cache_key, duration=60):
    """Set cooldown period for an action."""
    # Store a simple value (e.g., True) with an expiration time. The actual value is not important.
    cache.set(cache_key, True, duration)


def send_email_safe(to_email, subject, content, error_context=""):
    """Send email with error handling. Returns (success: bool, error_message or None)."""
    try:
        send_email(to_email, subject, content)
        return True, None
    except Exception as e:
        logger.exception("Failed to send email to %s (%s): %s", to_email, error_context, e)
        return False, "Email failed to send. Please try again."


def handle_error(request, message, is_service_error=False):
    """Unified error handling for both HTML and JSON requests."""
    if is_json_request(request):
        status_code = 400 if is_service_error else 500
        return json_response('error', message, http_status=status_code)
    messages.error(request, message)
    return None


def get_session_user_id(request, session_key='unverified_user_id'):
    """Get user ID from session or return None."""
    return request.session.get(session_key)


def clear_session_key(request, session_key='unverified_user_id'):
    """Remove key from session."""
    request.session.pop(session_key, None)

@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.method != 'POST':
        if is_json_request(request):
            return json_response('success', 'Login endpoint ready.', data={'method': 'POST'})
        return render(request, 'accounts/login.html', {
            'form': LoginForm(),
            'GOOGLE_CLIENT_ID': getattr(settings, 'GOOGLE_CLIENT_ID', ''),
        })

    form = LoginForm(request.POST)
    ip = get_ip(request)
    username = request.POST.get('username', '').strip()
    ratelimit_key = f"login_fail_{ip}_{username}" if username else f"login_fail_{ip}"

    try:
        check_ratelimit(ratelimit_key, limit=10, period=60)
    except RateLimitError as e:
        if is_json_request(request):
            return json_response('error', str(e), http_status=429)
        messages.error(request, str(e))
        return render(request, 'accounts/login.html', {'form': form})
    
    if not form.is_valid():
        messages.error(request, "Please fill in both fields.")
        return render(request, 'accounts/login.html', {'form': form})

    dto = schemas.LoginDTO(
        username=form.cleaned_data['username'],
        password=form.cleaned_data['password'],
    )
    user, status = services.login_service(request, dto)

    # 1. Handle Successful Login
    if status == "success":
        login(request, user)
        cache.delete(f"ratelimit:{ratelimit_key}")
        if is_json_request(request):
            return json_response('success', data={'user': user.username})
        
        from django.utils.http import url_has_allowed_host_and_scheme
        next_url = request.GET.get("next", "")
        # Use the secure helper to verify the URL belongs to your site
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url, 
            allowed_hosts={request.get_host()}, 
            require_https=request.is_secure()
        ):
            return redirect(next_url)
        return redirect('dashboard')

    # 2. Handle Unverified Status
    if status == "unverified" and user:
        if is_json_request(request):
            return json_response('error', 'Account unverified.', code=status, http_status=401)
        
        request.session['unverified_user_id'] = user.id
        # We don't add an error message here because the verification page 
        # usually handles its own "Please verify" messaging.
        return redirect('accounts:verify_registration')

    # 3. Handle Generic Failures / Invalid Credentials
    attempts_used = cache.get(f"ratelimit:{ratelimit_key}", 0)
    attempts_used = attempts_used if isinstance(attempts_used, int) else 0
    remaining = max(0, 10 - attempts_used)

    error_msg = "Invalid username or password."
    if 0 < remaining <= 3:
        error_msg += f" Warning: {remaining} attempts remaining."

    if is_json_request(request):
        return json_response('error', error_msg, code=status, http_status=401)

    messages.error(request, error_msg)
    return render(request, 'accounts/login.html', {
        'form': form,
        'GOOGLE_CLIENT_ID': getattr(settings, 'GOOGLE_CLIENT_ID', ''),
    })

def build_verification_email(name, code):
    return f"""
    <div style="font-family:Arial,sans-serif;padding:20px;">
        <h2>Planforge Verification</h2>

        <p>Hi {name},</p>

        <p>Your verification code is:</p>

        <div style="font-size:28px;font-weight:bold;letter-spacing:3px;">
            {code}
        </div>

        <p>This code expires in <strong>10 minutes</strong>.</p>

        <hr />
        <p style="color:gray;font-size:12px;">
            If you didn’t request this, ignore this email.
        </p>
    </div>
    """

@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.method != 'POST':
        if is_json_request(request):
            return json_response('success', 'Register endpoint ready.', data={'method': 'POST'})
        return render(request, 'accounts/register.html', {
            'form': SignUpForm(),
            'GOOGLE_CLIENT_ID': getattr(settings, 'GOOGLE_CLIENT_ID', ''),
        })

    #get the user's IP address for rate limiting 
    ip = get_ip(request)
    try:
        #if too many registration attempts from this IP, show rate limit error
        check_ratelimit(f"reg_ip_{ip}", limit=50, period=3600)
    except RateLimitError as e:
        if is_json_request(request):
            return json_response('error', str(e), http_status=429)
        messages.error(request, str(e))
        return redirect('accounts:register')

    #parse request data from POST or JSON body
    data = get_request_data(request)
    if data is None:
        return json_response('error', 'Invalid JSON', http_status=400)

    #validate the registration form
    form = SignUpForm(data)
    if not form.is_valid():
        if is_json_request(request):
            return json_response('error', 'Validation failed', data={'errors': form.errors}, http_status=400)
        messages.error(request, "Please check the form.")
        return render(request, 'accounts/register.html', {'form': form})

    try:
        #build the RegisterDTO using the cleaned form data
        dto = schemas.RegisterDTO(
            username=form.cleaned_data['username'],
            email=form.cleaned_data['email'],
            password=form.cleaned_data['password'],
            first_name=form.cleaned_data.get('first_name', ''),
            last_name=form.cleaned_data.get('last_name', '')
        )
        #call the register_user service 
        user, code = services.register_user(dto)

        #store the unverified user ID in session
        request.session['unverified_user_id'] = user.id
    except services.ServiceError as e:
        if is_json_request(request):
            return json_response('error', str(e), http_status=400)
        messages.error(request, str(e))
        return render(request, 'accounts/register.html', {'form': form})

    # Fire the verification email asynchronously — the worker returns to the
    # client immediately. If delivery fails the user can request a resend.
    send_email_async(
        user.email,
        "Verify your Planforge account",
        build_verification_email(user.first_name, code),
        "registration",
    )

    if is_json_request(request):
        return json_response('success', 'Check email for code.', data={'email': user.email}, http_status=201)

    messages.success(request, f"Code sent to {user.email}")
    return redirect('accounts:verify_registration')


@require_http_methods(["GET", "POST"])
def verify_registration(request):
    #gets the user ID from the session to identify which user is trying to verify their account
    user_id = get_session_user_id(request)
    if not user_id:
        if is_json_request(request):
            return json_response('error', 'No registration session. Please register first.', http_status=401)
        return redirect('accounts:register')

    try:
        #fetches the user object from the database using the user ID
        user_obj = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        #if user does not exist, we clear the session and redirect to registration
        request.session.flush()
        if is_json_request(request):
            return json_response('error', 'User not found. Register again.', http_status=404)
        return redirect('accounts:register')

    #returns the verification form for GET requests
    if request.method != 'POST':
        if is_json_request(request):
            return json_response('success', 'Verification ready.', data={
                'email': user_obj.email,
                'required_fields': ['code']
            })
        form = VerifyCodeForm()
        return render(request, 'accounts/verify_registration.html', {'form': form, 'email': user_obj.email})

    # Handle POST requests
    if is_json_request(request):
        #parse request data from JSON body to get the verification code submitted by the user
        data = get_request_data(request)
        if data is None:
            return json_response('error', 'Invalid JSON', http_status=400)
        code = data.get('code')
    else:
        # Use Django form for HTML requests
        form = VerifyCodeForm(request.POST)
        if not form.is_valid():
            return render(request, 'accounts/verify_registration.html', {'form': form, 'email': user_obj.email})
        code = form.cleaned_data['code']

    try:
        #build the VerifyCodeDTO with the user ID and submitted code
        dto = schemas.VerifyCodeDTO(user_id=user_id, code=code)
        
        #calls the verify_code service to check if the code is correct and activate the account if it is
        success, msg = services.verify_code(dto, acting_user_id=user_id)

        if is_json_request(request):
            if success:
                #on successful verification, clear the session key to clean up
                clear_session_key(request)
                return json_response('success', msg)
            return json_response('error', msg, http_status=400)

        if success:
            messages.success(request, msg)
            #on successful verification, clear the session key to clean up and redirect to login
            clear_session_key(request)
            return redirect('accounts:login')

        messages.error(request, msg)

    except services.ServiceError as e:
        #Catches expected service errors like "Invalid code" or "Code expired" 
        if is_json_request(request):
            return json_response('error', str(e), http_status=400)
        messages.error(request, str(e))
    except Exception as e:
        #Catches unexpected errors and logs them for debugging. The user gets a generic error message.
        logger.exception("Verification error for user_id=%s: %s", user_id, e)
        if is_json_request(request):
            return json_response('error', 'Verification failed. Try again.', http_status=500)
        messages.error(request, "Verification failed. Try again.")

    #user_obj.email is included in the context to show the user which email they need to check for the verification code
    if is_json_request(request):
        return json_response('error', 'Verification failed.', http_status=400)
    form = VerifyCodeForm()
    return render(request, 'accounts/verify_registration.html', {'form': form, 'email': user_obj.email})


@require_http_methods(["GET", "POST"])
def resend_code(request):
    #gets the user ID from the session to identify which user is trying to resend the verification code
    user_id = get_session_user_id(request)

    #if there is no user ID in the session, it means there is no active registration process
    if not user_id:
        if is_json_request(request):
            return json_response('error', 'Session expired. Register again.', http_status=401)
        return redirect('accounts:register')

    #handles GET requests
    if request.method == "GET":
        if is_json_request(request):
            return json_response('ready', 'Send POST to resend code.')
        return redirect('accounts:verify_registration')

    # No separate cache cooldown here — services.resend_code() enforces
    # DB-backed exponential backoff that survives Redis restarts.
    try:
        #build the ResendCodeDTO with the user ID from the session
        dto = schemas.ResendCodeDTO(user_id=user_id)

        #call the resend_code service to generate a new verification code and get the associated email address
        success, code_or_error, email = services.resend_code(dto)

        #if the service fails to generate a new code, handle the error by showing an appropriate message to the user
        if not success:
            error_msg = code_or_error if isinstance(code_or_error, str) else "Failed to generate code."
            if is_json_request(request):
                return json_response('error', error_msg, http_status=400)
            messages.error(request, error_msg)
            return redirect('accounts:verify_registration')

    except services.ServiceError as e:
        # Catches cooldown errors ("Please wait N seconds.") from the service
        if is_json_request(request):
            return json_response('error', str(e), http_status=429)
        messages.warning(request, str(e))
        return redirect('accounts:verify_registration')

    except Exception as e:
        # Catches unexpected errors and logs them for debugging.
        logger.exception("Code generation failed for user_id=%s: %s", user_id, e)
        if is_json_request(request):
            return json_response('error', 'Failed to generate code.', http_status=500)
        messages.error(request, "Failed to generate code.")
        return redirect('accounts:verify_registration')

    #send the new verification code to the user's email address asynchronously
    send_email_async(
        email,
        "Your new Planforge verification code",
        build_verification_email("there", code_or_error),
        "resend",
    )

    if is_json_request(request):
        return json_response('success', 'Code resent')

    messages.success(request, "Code resent.")
    return redirect('accounts:verify_registration')


@login_required
@require_http_methods(["GET", "POST"])
def verify_email_change(request):
    #handles GET requests 
    if request.method != 'POST':
        if is_json_request(request):
            return json_response('ready', 'Send POST with "code" to verify.')
        return render(request, 'accounts/verify_email_change.html')

    #parse request data from POST or JSON body
    data = get_request_data(request)
    if data is None:
        return json_response('error', 'Invalid JSON', http_status=400)

    #extract the verification code from the request data
    code = data.get('code')

    try:
        #build the VerifyEmailChangeDTO with the user ID from the request and the submitted code
        dto = schemas.VerifyEmailChangeDTO(user_id=request.user.id, code=code)

        #call the verify_email_change service 
        success, msg = services.verify_email_change(dto)

        #if success, refresh the user object from the database to get the updated email
        if is_json_request(request):
            return json_response('success' if success else 'error', msg,
            http_status=200 if success else 400)
        if success:
            messages.success(request, msg)
            return redirect('accounts:profile')

        messages.error(request, msg)

    except Exception as e:
        #Catches unexpected errors during email change verification and logs them for debugging. 
        logger.exception("Email change verification failed for user_id=%s: %s", request.user.id, e)
        if is_json_request(request):
            return json_response('error', 'Verification failed.', http_status=500)
        messages.error(request, "Verification failed.")

    return redirect('accounts:verify_email_change')


@login_required
@require_http_methods(["GET", "POST"])
def password_change_view(request):
    #handles GET requests
    if request.method != 'POST':
        if is_json_request(request):
            return json_response('ready', data={'required_fields': ['old_password', 'new_password', 'confirm_new_password']})
        return render(request, 'accounts/password_change_form.html')

    #parse request data from POST or JSON body
    data = get_request_data(request)

    if data is None:
        if is_json_request(request):
            return json_response('error', 'Invalid JSON', http_status=400)
        messages.error(request, "Invalid request.")
        return render(request, 'accounts/password_change_form.html')

    try:
        #build the PasswordChangeDTO 
        dto = schemas.PasswordChangeDTO(
            user_id=request.user.id,
            old_password=data.get('old_password'),
            new_password=data.get('new_password'),
            confirm_new_password=data.get('confirm_new_password')
        )
        #call the change_password service to attempt to change the user's password
        success, msg = services.change_password(request.user, dto)

        #raise a ValueError if the password change was not successful
        if not success:
            raise ValueError(msg)

        #on successful password change, refresh the user object from the database to get the updated password hash
        request.user.refresh_from_db()
        #update the session auth hash to keep the user logged in after the password change
        update_session_auth_hash(request, request.user)

        if is_json_request(request):
            return json_response('success', msg)

        messages.success(request, msg)
        return redirect('accounts:profile')

    except ValueError as e:
        #Catches expected validation errors from the service
        if is_json_request(request):
            return json_response('error', str(e), http_status=400)
        messages.error(request, str(e))
        return render(request, 'accounts/password_change_form.html')


@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def delete_account_view(request):
    #handles GET requests to show the account deletion confirmation page
    if request.method not in ('POST', 'DELETE'):
        if is_json_request(request):
            return json_response('ready', 'Send POST with "password" to delete.')
        return render(request, 'accounts/delete_account.html')

    #parse request data from POST or JSON body
    data = get_request_data(request)
    if data is None:
        return json_response('error', 'Invalid JSON', http_status=400)

    #extract the password from the request data to confirm the user's identity before deleting the account
    password = data.get('password')

    try:
        #build the DeleteAccountDTO
        dto = schemas.DeleteAccountDTO(user_id=request.user.id, password=password)

        #call the delete_account service to attempt to delete the user's account
        services.delete_account(dto)
        #if deletion is successful, log the user out to end their session
        logout(request)

        if is_json_request(request):
            return json_response('success', 'Account deleted')
        messages.info(request, "Account deleted.")
        return redirect('accounts:register')

    except Exception as e:
        #Catches any errors during account deletion and logs them for debugging. 
        logger.exception("Account deletion failed for user_id=%s: %s", request.user.id, e)
        if is_json_request(request):
            return json_response('error', str(e), http_status=400)
        messages.error(request, str(e))
        return render(request, 'accounts/delete_account.html')


@require_POST
def logout_view(request):
    logout(request)
    if is_json_request(request):
        return json_response('success', 'Logged out.')
    return redirect('accounts:login')


@require_POST
def cancel_registration(request):
    # lets a user abandon registration and clean up.
    #gets the user ID from the session to identify which registration process to cancel
    uid = get_session_user_id(request)
    #if there is a user ID in the session
    if uid:
        try:
            #fetches the user object from the database using the user ID
            user = User.objects.get(id=uid)

            #if the user is found but not active
            if not user.is_active:
                #deletes the user object from the database to cancel the registration
                user.delete()

        except User.DoesNotExist:
            #if the user does not exist, we just ignore it and proceed to clear the session
            pass
        finally:
            #clear the session to remove any registration state and redirect to the registration page
            request.session.flush()
    return redirect('accounts:register')


@login_required
@require_POST
def resend_verification_code_profile(request):
    #create a cache key for rate limiting the resend action to prevent abuse
    cache_key = f"email_change_resend_cooldown_{request.user.id}"
    #check if the user is currently in a cooldown
    if check_cooldown(cache_key):
        msg = "Please wait a minute before requesting another code."
        if is_json_request(request):
            return json_response('error', msg, http_status=429)
        messages.warning(request, msg)
        return redirect('accounts:verify_email_change')

    try:
        #call the resend_email_change_code service
        success, result = services.resend_email_change_code(request.user.id)

        #if the service fails to generate a new code, show an appropriate error message to the user
        if not success:
            if is_json_request(request):
                return json_response('error', result, http_status=400)
            messages.warning(request, result)
            return redirect('accounts:verify_email_change')

        #result contains the new verification code and the email address it is associated with
        raw_code, email_to = result

        #send the new verification code to the user's email address asynchronously
        send_email_async(
            email_to,
            "Your New Planforge Code",
            f"<p>Your new verification code is: <strong>{raw_code}</strong></p>",
            "email_change_resend",
        )

        #set a cooldown in cache to prevent the user from spamming the resend action
        set_cooldown(cache_key, 60)

        if is_json_request(request):
            return json_response('success', 'Code resent')

        messages.success(request, f"New code sent to {email_to}")

    except UserProfile.DoesNotExist:
        #if the user's profile is missing, log an error and show a message to the user. 
        logger.error("UserProfile missing for user_id=%s", request.user.id)
        if is_json_request(request):
            return json_response('error', 'Profile not found.', http_status=404)
        messages.error(request, "Profile not found.")
    
    except Exception as e:
        #Catches unexpected errors during the resend process and logs them for debugging. 
        logger.exception("Resend failed for user_id=%s: %s", request.user.id, e)
        if is_json_request(request):
            return json_response('error', 'Something went wrong.', http_status=500)
        messages.error(request, "Something went wrong.")

    return redirect('accounts:verify_email_change')

@login_required
def _handle_email_change_request(request):
    #create a cache key for rate limiting the email change request to prevent abuse
    cache_key = f"email_init_cooldown_{request.user.id}"

    #check if the user is currently in a cooldown period for requesting an email change
    if check_cooldown(cache_key):
        msg = "Please wait a minute before requesting another code."
        if is_json_request(request):
            return json_response('error', msg, http_status=429)
        messages.warning(request, msg)
        return redirect('accounts:profile')

    try:
        #build the EmailChangeRequestDTO
        dto = schemas.EmailChangeRequestDTO(
            user_id=request.user.id,
            new_email=request.POST.get('email', '').strip(),
            current_email=request.user.email
        )
        #call the request_email_change service
        raw_code = services.request_email_change(dto)

    except (services.ServiceError, ValueError) as e:
        #Catches expected service errors
        if is_json_request(request):
            return json_response('error', str(e), http_status=400)
        messages.error(request, str(e))
        return redirect('accounts:profile')

    #send the email change verification code to the new email address asynchronously
    send_email_async(
        dto.new_email,
        "Confirm your Planforge email change",
        f"<p>Your email change code is: <strong>{raw_code}</strong></p>",
        "email_change",
    )

    #set a cooldown in cache to prevent the user from spamming email change requests
    set_cooldown(cache_key, 60)

    if is_json_request(request):
        return json_response('success', 'Verification code sent.')

    return redirect('accounts:verify_email_change')

@login_required
def _handle_profile_update(request, profile):
    #the email field is not included in the profile update form because it requires a separate verification process
    post_data = request.POST.copy()
    post_data['email'] = request.user.email

    #fills the ProfileUpdateForm with the submitted data and the current user instance
    form = ProfileUpdateForm(post_data, instance=request.user)

    #validate the form data and if invalid, show error messages. 
    if not form.is_valid():
        if is_json_request(request):
            return json_response('error', 'Validation failed', data={'errors': form.errors}, http_status=400)
        messages.error(request, "Please correct the errors below.")
        return render(request, 'accounts/profile.html', {'form': form, 'profile': profile})

    try:
        #save the updated user information to the database.
        form.save()

    except IntegrityError:
        #if the username is already taken by another user, show an error message. 
        msg = "That username is already taken."
        if is_json_request(request):
            return json_response('error', msg, http_status=400)
        messages.error(request, msg)
        return render(request, 'accounts/profile.html', {'form': form, 'profile': profile})

    if is_json_request(request):
        return json_response('success', data={
            'username':   request.user.username,
            'first_name': request.user.first_name,
            'last_name':  request.user.last_name,
            'email':      request.user.email,
        })

    messages.success(request, 'Profile updated.')
    return redirect('accounts:profile')

@login_required
@require_http_methods(["GET", "POST"])
def profile_settings(request):
    try:
        #fetches the user's profile from the database 
        profile = UserProfile.objects.get(user=request.user)

    except UserProfile.DoesNotExist:
        #if the profile is missing, log an error and show a message to the user
        logger.error("UserProfile missing for user_id=%s", request.user.id)
        messages.error(request, "Profile not found. Please contact support.")
        return redirect('dashboard')

    if request.method != 'POST':
        if is_json_request(request):
            return json_response('success', data={
                'username':   request.user.username,
                'first_name': request.user.first_name,
                'last_name':  request.user.last_name,
                'email':      request.user.email,
            })
        return render(request, 'accounts/profile.html', {
            'form':    ProfileUpdateForm(instance=request.user),
            'profile': profile
        })

    #if request_email_change is in POST data, it means the user is trying to change their email address
    if 'request_email_change' in request.POST:
        return _handle_email_change_request(request)
    #if not, it means the user is trying to update their profile information like username or name fields
    return _handle_profile_update(request, profile)

# PASSWORD RESET
# Django's built-in password reset flow, pointed at our templates.

class PlanforgePasswordResetView(PasswordResetView):
    #uses custom templates for the password reset process
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/password_reset_email.html"
    subject_template_name = "accounts/password_reset_subject.txt"
    #success URL is where the user is redirected after successfully submitting the password reset form
    success_url = reverse_lazy("accounts:password_reset_done")

    #override the send_mail method to customize how the password reset email is sent
    def send_mail(self, subject_template_name, email_template_name,
                  context, from_email, to_email, html_email_template_name=None):

        # Production — send real email
        subject = render_to_string(subject_template_name, context).strip()
        html_content = render_to_string(email_template_name, context)
        
        send_email(to_email, subject, html_content)

class PlanforgePasswordResetDoneView(PasswordResetDoneView):
    #shows email sent page
    template_name = "accounts/password_reset_done.html"


class PlanforgePasswordResetConfirmView(PasswordResetConfirmView):
    #shows page where user enters new password
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class PlanforgePasswordResetCompleteView(PasswordResetCompleteView):
    #shows page confirming password has been reset
    template_name = "accounts/password_reset_complete.html"


# SET PASSWORD (for Google users who don't have one yet)
@login_required
@require_http_methods(["GET", "POST"])
def set_password_view(request):
    """
    Lets a user who signed up via Google set a password so they can also
    log in with username + password. Only shown/accessible when the user
    has no usable password.
    """
    if request.user.has_usable_password():
        # Already has a password — send them to the normal change-password page.
        return redirect('accounts:change_password')

    if request.method != 'POST':
        return render(request, 'accounts/set_password.html')

    new_password = request.POST.get('new_password', '')
    confirm_password = request.POST.get('confirm_password', '')

    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    if new_password != confirm_password:
        messages.error(request, "Passwords do not match.")
        return render(request, 'accounts/set_password.html')
    
    try:
        validate_password(new_password, request.user)
    except DjangoValidationError as e:
        for err in e.messages:
            messages.error(request, err)
        return render(request, 'accounts/set_password.html')

    request.user.set_password(new_password)
    request.user.save()
    # Keep the user logged in after setting their password
    update_session_auth_hash(request, request.user)
    messages.success(request, "Password set! You can now sign in with your username and password.")
    return redirect('accounts:profile')


# GOOGLE OAUTH (standard redirect flow — no GSI JavaScript library)
import urllib.parse
import secrets
import requests as _requests

#where the user gets sent to first
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

#where the server later exchanges the code for tokens
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

#where the server fetches the user's profile using the access token
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def google_oauth_view(request):
    """
    Step 1: Build the Google authorisation URL and redirect the user there.
    A random `state` token is stored in the session to prevent CSRF.
    """
    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
    if not client_id:
        messages.error(request, "Google sign-in is not configured.")
        return redirect('accounts:login')

    # Build the absolute callback URL, e.g. http://localhost:8000/accounts/google/callback/
    redirect_uri = request.build_absolute_uri('/accounts/google/callback/')

    # CSRF protection: store a random state value in the session
    state = secrets.token_urlsafe(32)
    request.session['google_oauth_state'] = state

    # If the user is already logged in, flag this as a connect request (not login/signup)
    if request.user.is_authenticated:
        request.session['google_connect_user_id'] = request.user.id

    # Preserve ?next= so we can redirect there after login
    next_url = request.GET.get('next', '')
    if next_url:
        request.session['google_oauth_next'] = next_url

    #Build the Google OAuth URL with the necessary query parameters
    params = urllib.parse.urlencode({
        'client_id': client_id, # identifies your app to Google
        'redirect_uri': redirect_uri, # tells Google where to send the user back
        'response_type': 'code', # says you want an authorization code back, not tokens directly
        'scope': 'openid email profile', # asks permission for: OpenID identity, email, profile info
        'state': state, # security token to verify callback is genuine
        'access_type': 'online', # says this is normal online access, usually without long-term refresh behavior
        # Always show the google account chooser even if the browser has a cached google session
        'prompt': 'select_account',
    })
    return redirect(f"{GOOGLE_AUTH_URL}?{params}")

def google_callback_view(request):
    """
    Step 2: Google redirects back here with ?code=...&state=...
    Exchange the code for tokens, fetch the user's profile, then
    log them in (returning user) or redirect to username picker (new user).

    Security measures applied:
      - Rate limited per IP to block code-stuffing attacks
      - State token validated to prevent CSRF
      - next= redirect validated with url_has_allowed_host_and_scheme()
        to block open redirect attacks (startswith('/') alone can be
        bypassed with paths like //evil.com or /\\evil.com)
    """
    from django.utils.http import url_has_allowed_host_and_scheme

    # SECURITY: Rate-limit the callback endpoint per IP.
    # Prevents attackers from hammering it with forged/replayed codes.
    ip = get_ip(request)
    try:
        check_ratelimit(f"google_callback_{ip}", limit=20, period=60)
    except RateLimitError as e:
        messages.error(request, str(e))
        return redirect('accounts:login')

    # SECURITY: Validate the state token to prevent CSRF.
    # The state was generated in google_oauth_view and stored in the session.
    # If it doesn't match what Google sent back, the request is forged.
    stored_state = request.session.pop('google_oauth_state', None)
    returned_state = request.GET.get('state', '')
    if not stored_state or stored_state != returned_state:
        messages.error(request, "Invalid state. Please try signing in again.")
        return redirect('accounts:login')

    error = request.GET.get('error')
    if error:
        messages.error(request, "Google sign-in was cancelled or failed.")
        return redirect('accounts:login')

    code = request.GET.get('code')
    if not code:
        messages.error(request, "No authorisation code received from Google.")
        return redirect('accounts:login')

    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
    client_secret = getattr(settings, 'GOOGLE_CLIENT_SECRET', '')
    redirect_uri = request.build_absolute_uri('/accounts/google/callback/')

    # Exchange the authorisation code for an access token
    try:
        token_resp = _requests.post(GOOGLE_TOKEN_URL, data={
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }, timeout=10)
        token_resp.raise_for_status() # 
        token_data = token_resp.json()
    except Exception as e:
        logger.exception("Google token exchange failed: %s", e)
        messages.error(request, "Could not connect to Google. Please try again.")
        return redirect('accounts:login')

    access_token = token_data.get('access_token')
    if not access_token:
        messages.error(request, "Google did not return an access token.")
        return redirect('accounts:login')

    # Fetch the user's profile from Google's userinfo endpoint
    try:
        userinfo_resp = _requests.get(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
        userinfo_resp.raise_for_status()
        userinfo = userinfo_resp.json()
    except Exception as e:
        logger.exception("Google userinfo fetch failed: %s", e)
        messages.error(request, "Could not retrieve your Google profile.")
        return redirect('accounts:login')

    google_email = userinfo.get('email', '').lower()
    google_first_name = userinfo.get('given_name', '')
    google_last_name = userinfo.get('family_name', '')
    google_sub = userinfo.get('sub', '')
    google_avatar = userinfo.get('picture', '')

    if not google_email:
        messages.error(request, "Could not retrieve your email from Google.")
        return redirect('accounts:login')

    # CONNECT FLOW (user was already logged in when they clicked "Connect")
    connect_user_id = request.session.pop('google_connect_user_id', None)
    if connect_user_id:
        try:
            current_user = User.objects.get(pk=connect_user_id)
        except User.DoesNotExist:
            messages.error(request, "Session expired. Please sign in and try again.")
            return redirect('accounts:login')

        # Block if the Google email doesn't match this account's email.
        # Users may only connect a Google account that shares their Planforge email.
        if google_email != current_user.email.lower():
            messages.error(
                request,
                f"You can only connect a Google account that uses your Planforge email "
                f"({current_user.email}). The selected Google account uses a different address."
            )
            return redirect('accounts:profile')

        # Block if somehow that email belongs to a *different* Planforge account (edge case)
        conflicting = User.objects.filter(email__iexact=google_email).exclude(pk=current_user.pk).first()
        if conflicting:
            messages.error(
                request,
                "That Google account is already linked to a different Planforge account."
            )
            return redirect('accounts:profile')

        # All clear — attach Google to the current account
        profile, _ = UserProfile.objects.get_or_create(user=current_user)
        profile.google_connected = True
        if google_avatar:
            profile.avatar_url = google_avatar
        profile.save(update_fields=['google_connected', 'avatar_url'])
        messages.success(request, "Google account connected successfully.")
        return redirect('accounts:profile')

    # LOGIN / SIGNUP FLOW (user was not logged in)

    # Returning user — update avatar + mark google_connected, then log in
    existing = User.objects.filter(email__iexact=google_email).first()
    if existing:
        # Keep avatar and google_connected fresh on every Google login
        profile, _ = UserProfile.objects.get_or_create(user=existing)
        profile.google_connected = True
        if google_avatar:
            profile.avatar_url = google_avatar
        profile.save(update_fields=['google_connected', 'avatar_url'])

        # This tells Django which authentication backend to use, then logs the user in.
        existing.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, existing)

        # SECURITY: Validate the next URL properly.
        # startswith('/') alone can be bypassed with //evil.com or /\evil.com.
        # url_has_allowed_host_and_scheme() is Django's built-in safe redirect check.
        next_url = request.session.pop('google_oauth_next', '')
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect('dashboard')

    # New user — stash profile in session, redirect to username picker
    request.session['google_oauth'] = {
        'email': google_email,
        'first_name': google_first_name,
        'last_name': google_last_name,
        'sub': google_sub, # Google's unique identifier for the user
        'avatar': google_avatar,
    }
    return redirect('accounts:google_username')


@require_http_methods(["GET", "POST"])
def google_username_view(request):
    """
    Step 2 of Google sign-in (new users only).
    Lets the user pick a username, then creates their account.
    """
    oauth_data = request.session.get('google_oauth')
    if not oauth_data:
        # Session expired or user navigated here directly.
        return redirect('accounts:login')

    def render_form(username=''):
        return render(request, 'accounts/google_username.html', {
            'email': oauth_data['email'],
            'first_name': oauth_data['first_name'],
            'username': username,
        })
    
    if request.method == 'GET':
        return render_form()

    # POST — validate and create account.
    username = request.POST.get('username', '').strip()

    if not username:
        messages.error(request, "Please enter a username.")
        return render_form()

    if len(username) < 3 or len(username) > 30:
        messages.error(request, "Username must be between 3 and 30 characters.")
        return render_form(username)

    import re
    if not re.match(r'^[\w.@+-]+$', username):
        messages.error(request, "Username may only contain letters, numbers, and @/./+/-/_ characters.")
        return render_form(username)

    if User.objects.filter(username__iexact=username).exists():
        messages.error(request, "That username is already taken. Please choose another.")
        return render_form(username)

    try:
        user = User.objects.create_user(
            username = username,
            email = oauth_data['email'],
            first_name = oauth_data['first_name'],
            last_name = oauth_data['last_name'],
            # No password — Google is their auth provider.
            # set_unusable_password() prevents password-based login.
            password = None,
        )
        user.is_active = True
        user.save()
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.google_connected = True
        if oauth_data.get('avatar'):
            profile.avatar_url = oauth_data['avatar']
        profile.save(update_fields=['google_connected', 'avatar_url'])
    except IntegrityError:
        # Two simultaneous requests passed the exists() check above before either
        # committed — the second one hits the DB unique constraint. Surface a clean
        # message instead of a 500.
        messages.error(request, "That username was just taken. Please choose another.")
        return render_form(username)
    except Exception as e:
        logger.exception("Google account creation failed: %s", e)
        messages.error(request, "Account creation failed. Please try again.")
        return render_form(username)

    # Clean up session and log the user in.
    del request.session['google_oauth']
    user.backend = 'django.contrib.auth.backends.ModelBackend'
    login(request, user)
    messages.success(request, f"Welcome to Planforge, {user.first_name}!")
    return redirect('dashboard')

# DISCONNECT GOOGLE

@login_required
@require_POST
def disconnect_google_view(request):
    """
    Removes the Google connection from the account.
    Only allowed if the user already has a password — otherwise they would
    be completely locked out with no way to sign in.
    """
    if not request.user.has_usable_password():
        messages.error(
            request,
            "Set a password first before disconnecting Google — "
            "otherwise you won't be able to sign in."
        )
        return redirect('accounts:profile')

    try:
        profile = request.user.userprofile
        profile.google_connected = False
        profile.avatar_url = None
        profile.save(update_fields=['google_connected', 'avatar_url'])
        messages.success(request, "Google has been disconnected from your account.")
    except Exception as e:
        logger.exception("disconnect_google failed for user_id=%s: %s", request.user.id, e)
        messages.error(request, "Something went wrong. Please try again.")

    return redirect('accounts:profile')

@login_required
@require_POST
def update_digest_preference(request):
    frequency = request.POST.get("digest_frequency", "weekly")
    allowed = {"daily", "weekly", "never"}

    if frequency not in allowed:
        frequency = "weekly"

    profile = request.user.userprofile
    profile.digest_frequency = frequency
    profile.save(update_fields=["digest_frequency"])

    messages.success(request, "Email preference saved.")
    return redirect("accounts:profile")

# ERROR HANDLERS 

def custom_400_handler(request, exception=None):
    if is_json_request(request):
        return json_response('error', 'Bad Request', http_status=400)
    return render(request, 'errors/400.html', status=400)


def custom_403_handler(request, exception=None):
    if is_json_request(request):
        return json_response('error', 'Forbidden', http_status=403)
    return render(request, 'errors/403.html', status=403)


def custom_404_handler(request, exception):
    if is_json_request(request):
        return json_response('error', 'Not Found', http_status=404)
    return render(request, 'errors/404.html', status=404)


def custom_500_handler(request):
    if is_json_request(request):
        return json_response('error', 'Server Error', http_status=500)
    return render(request, 'errors/500.html', status=500)