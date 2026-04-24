import logging
from datetime import timedelta
from django.contrib.auth import get_user_model, authenticate
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from .models import UserProfile
from .schemas import (
    LoginDTO,
    VerifyCodeDTO,
    ResendCodeDTO,
    EmailChangeRequestDTO,
    VerifyEmailChangeDTO,
    PasswordChangeDTO,
    DeleteAccountDTO,
)

#this gets the current django user model
User = get_user_model()

#creates a logger for this file, so we can log important events and errors in a consistent way. 
logger = logging.getLogger(__name__)

class ServiceError(Exception):
    pass

#custom exception for permission-related issues
class PermissionError(ServiceError):
    pass


import hashlib
from django.contrib.auth import authenticate
from django.db import transaction


def _hash_code(raw_code: str) -> str:
    """Fast SHA-256 hash for short-lived verification codes.
    
    We intentionally do NOT use bcrypt/PBKDF2 here because:
    - These codes are 6 digits, expire in 10 minutes, and have brute-force
      protection (max attempts). The attack surface is tiny.
    - bcrypt takes ~100-300ms per call. For codes, that cost buys nothing.
    - SHA-256 is cryptographically strong and effectively instantaneous.
    
    Never use this for long-lived secrets like user passwords.
    """
    return hashlib.sha256(raw_code.encode()).hexdigest()


def _verify_code(raw_code: str, stored_hash: str) -> bool:
    """Constant-time comparison for SHA-256 hashed verification codes."""
    import hmac
    return hmac.compare_digest(
        _hash_code(raw_code),
        stored_hash,
    )

def register_user(dto):
    with transaction.atomic():
        # # Purge any unverified squatter account on this email before checking uniqueness.
        User.objects.filter(email__iexact=dto.email, is_active=False).delete()

        existing_user = User.objects.filter(email__iexact=dto.email).first()

        if existing_user:
            if existing_user.is_active:
                raise ServiceError("Email already registered.")
            
            profile, _ = UserProfile.objects.get_or_create(user=existing_user)
            if profile.code_generated_at and timezone.now() < (profile.code_generated_at + timedelta(minutes=10)):
                raise ServiceError("Please wait before requesting a new code.")
            
            if User.objects.filter(username__iexact=dto.username).exclude(id=existing_user.id).exists():
                raise ServiceError("Username taken.")
            
            existing_user.username = dto.username
            existing_user.set_password(dto.password) # Slow Hash (Required)
            existing_user.first_name = dto.first_name
            existing_user.last_name = dto.last_name
            existing_user.save()
            user = existing_user
        else:
            if User.objects.filter(username__iexact=dto.username, is_active=True).exists():
                raise ServiceError("Username taken.")

            user = User.objects.create_user(
                username=dto.username,
                email=dto.email,
                password=dto.password, # Slow Hash (Required)
                first_name=dto.first_name,
                last_name=dto.last_name,
                is_active=False
            )

        profile, _ = UserProfile.objects.get_or_create(user=user)
        raw_code = get_random_string(6, allowed_chars='0123456789')
        
        # SPEED OPTIMIZATION: Use SHA-256 for the short-lived code
        # Much faster than make_password() while remaining unreadable in the DB
        profile.email_verification_code = _hash_code(raw_code)
        profile.code_generated_at = timezone.now()
        profile.save()

        return user, raw_code

def login_service(request, data: LoginDTO):
    # this hashes ONLY ONCE because of the custom backend
    user = authenticate(request, username=data.username, password=data.password)
    
    if user:
        if not user.is_active:
            return user, "unverified"
        return user, "success"

    # Quick check for Google accounts (no hashing involved)
    potential_user = User.objects.filter(username=data.username).first()
    if potential_user and not potential_user.has_usable_password():
        return potential_user, "google_account"

    return None, "invalid"

def verify_code(data: VerifyCodeDTO, acting_user_id: int = None):
    # if an acting user id is provided and it doesn’t match the target user id, block it
    if acting_user_id and acting_user_id != data.user_id:
        raise PermissionError("Security Alert: Authorization failed.")

    try:
        #fetches user and profile, checks if user exists
        user = User.objects.get(id=data.user_id)
        profile = user.userprofile

        #checks if there is no pending verification
        if not profile.email_verification_code:
            raise ServiceError("No verification pending.")

        # Brute-force guard: too many wrong guesses → invalidate the code.
        # The attacker must now trigger a new code, which is rate-limited via
        # the resend cooldown. Resets to 0 on every new code issue.
        if profile.verify_attempts >= profile.MAX_VERIFY_ATTEMPTS:
            profile.email_verification_code = None
            profile.verify_attempts = 0
            profile.save()
            return False, "Too many incorrect attempts. Please request a new code."

        # Check code has not expired (10-minute window)
        if profile.code_generated_at:
            expires_at = profile.code_generated_at + timedelta(minutes=10)
            if timezone.now() > expires_at:
                return False, "Verification code has expired. Please request a new one."

        #checks if the provided code does not match the hashed code in the database
        if not _verify_code(data.code, profile.email_verification_code):
            profile.verify_attempts += 1
            remaining = profile.MAX_VERIFY_ATTEMPTS - profile.verify_attempts
            profile.save()
            if remaining > 0:
                return False, f"Invalid verification code. {remaining} attempt(s) remaining."
            return False, "Invalid verification code. No attempts remaining — please try again later."

        #activates user account and clears verification code and resets resend count and cooldown
        user.is_active = True
        user.save()

        profile.email_verification_code = None
        profile.verify_attempts = 0
        profile.resend_count = 0
        profile.cooldown_until = None
        profile.save()
        return True, "Account verified. Please log in."
    except User.DoesNotExist:
        raise ServiceError("User not found.")


def resend_code(data: ResendCodeDTO):
    try:
        #fetches user and profile, checks if user exists
        user = User.objects.get(id=data.user_id)
        profile = user.userprofile
        now = timezone.now()

        #blocks too many resend attempts
        if profile.cooldown_until and now < profile.cooldown_until:
            wait = int((profile.cooldown_until - now).total_seconds())
            raise ServiceError(f"Please wait {wait} seconds.")

        #increases resend count and sets cooldown based on the number of attempts. 
        profile.resend_count += 1
        #exponential backoff with a max of 24 hours.
        next_cooldown = 1 if profile.resend_count <= 3 else 5 * (2 ** (profile.resend_count - 4))
        profile.cooldown_until = timezone.now() + timedelta(minutes=min(next_cooldown, 1440))

        #creates a new verification code, hashes it, and saves to profile with timestamp    
        raw_code = get_random_string(6, allowed_chars='0123456789')
        profile.email_verification_code = _hash_code(raw_code)
        profile.code_generated_at = timezone.now()
        profile.verify_attempts = 0  # fresh code = fresh attempt counter
        profile.save()

        return True, raw_code, user.email
    except User.DoesNotExist:
        raise ServiceError("User not found.")


def request_email_change(dto: EmailChangeRequestDTO):
    #checks if the email is active
    if User.objects.filter(email__iexact=dto.new_email).exists():
        raise ServiceError("This email address is already in use.")

    #fetches user profile
    profile = UserProfile.objects.get(user_id=dto.user_id)

    #checks if user is requesting too soon after last change
    if profile.last_email_change:
        time_since = timezone.now() - profile.last_email_change
        if time_since < timedelta(hours=24):
            remaining = timedelta(hours=24) - time_since
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(rem, 60)
            raise ServiceError(f"You can only change your email once every 24 hours. Please wait {hours}h {minutes}m.")

    #updates profile with pending email, resets resend count, and sets cooldown
    profile.pending_email = dto.new_email
    profile.resend_count = 1
    profile.cooldown_until = timezone.now() + timedelta(minutes=1)

    raw_code = get_random_string(6, allowed_chars='0123456789')
    profile.email_verification_code = _hash_code(raw_code)
    profile.code_generated_at = timezone.now() # timestamp for the new code, used to enforce expiration
    profile.verify_attempts = 0 # reset attempts for the new code
    profile.save()

    return raw_code


def verify_email_change(data: VerifyEmailChangeDTO):
    try:
        #fetches user and profile
        user = User.objects.get(id=data.user_id)
        profile = user.userprofile
    except User.DoesNotExist:
        return False, "User not found."

    #checks if there is no pending email change or verification code
    if not profile.pending_email or not profile.email_verification_code:
        return False, "No active email change request found."
    
    # Brute-force guard — same pattern as verify_code for registration.
    if profile.verify_attempts >= profile.MAX_VERIFY_ATTEMPTS:
        profile.email_verification_code = None
        profile.pending_email = None
        profile.verify_attempts = 0
        profile.save()
        return False, "Too many incorrect attempts. Your email change request has been cancelled. Please start again."
    
    # Enforce the 10-minute expiry window (code_generated_at is set by request_email_change)
    if profile.code_generated_at:
        expires_at = profile.code_generated_at + timedelta(minutes=10)
        if timezone.now() > expires_at:
            profile.email_verification_code = None
            profile.pending_email = None
            profile.verify_attempts = 0
            profile.save()
            return False, "Verification code has expired. Please request a new email change."
        
    if not _verify_code(data.code, profile.email_verification_code):
        profile.verify_attempts += 1
        remaining = profile.MAX_VERIFY_ATTEMPTS - profile.verify_attempts
        profile.save()
        if remaining > 0:
            return False, f"Invalid verification code. {remaining} attempt(s) remaining."
        return False, "Invalid verification code. No attempts remaining."    

    #apply the email change, update the last change timestamp, and clear pending fields and cooldown
    user.email = profile.pending_email
    user.save()

    profile.last_email_change = timezone.now()
    profile.email_verification_code = None
    profile.pending_email = None
    profile.resend_count = 0
    profile.cooldown_until = None
    profile.verify_attempts = 0
    profile.save()
    return True, "Email updated successfully."

def resend_email_change_code(user_id: int):
    try:
        #fetches user profile
        profile = UserProfile.objects.get(user_id=user_id)
    except UserProfile.DoesNotExist:
        return False, "Profile not found."
    
    #checks if there is a pending email change request
    if not profile.pending_email:
        return False, "No pending email change request found."

    #blocks too many resend attempts with exponential backoff cooldown
    if profile.cooldown_until and timezone.now() < profile.cooldown_until:
        wait = int((profile.cooldown_until - timezone.now()).total_seconds())
        return False, f"Please wait {wait // 60}m {wait % 60}s before resending."

    #increases resend count and sets cooldown based on the number of attempts.
    profile.resend_count += 1
    next_cooldown = 1 if profile.resend_count <= 3 else 5 * (2 ** (profile.resend_count - 4))
    profile.cooldown_until = timezone.now() + timedelta(minutes=min(next_cooldown, 1440))

    #creates a new verification code, hashes it, and saves to profile with timestamp
    raw_code = get_random_string(6, allowed_chars='0123456789')
    profile.email_verification_code = _hash_code(raw_code)
    profile.code_generated_at = timezone.now() # update timestamp for the new code
    profile.save()

    return True, (raw_code, profile.pending_email)

def change_password(user, data: PasswordChangeDTO):
    '''
    checks if the old password is correct before allowing the change.
    All validation of the new password (length, complexity, etc.) are done in the DTO's
    '''
    if not user.check_password(data.old_password):
        return False, "Old password is incorrect."

    user.set_password(data.new_password)
    user.save()
    return True, "Password changed successfully."


def delete_account(data: DeleteAccountDTO):
    #fetches user and checks password before deletion
    user = User.objects.get(id=data.user_id)
    if not user.check_password(data.password):
        raise ServiceError("Incorrect password.")
    #deletes the user account
    user.delete()
    return True, "Account deleted."