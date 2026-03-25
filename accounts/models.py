from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
# Create your models here.

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='userprofile')
    email_verification_code = models.CharField(max_length=128, null=True, blank=True)
    pending_email = models.EmailField(null=True, blank=True)
    code_generated_at = models.DateTimeField(null=True, blank=True)
    last_email_change = models.DateTimeField(null=True, blank=True)
    resend_count = models.IntegerField(default=0)
    cooldown_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Tracks wrong guesses against the current verification code.
    # After MAX_VERIFY_ATTEMPTS the code is invalidated — user must request a new one.
    # Reset to 0 whenever a new code is issued or a correct code is submitted.
    verify_attempts = models.PositiveSmallIntegerField(default=0)

    # Google OAuth fields
    google_connected = models.BooleanField(default=False)
    avatar_url = models.URLField(max_length=500, null=True, blank=True)

    MAX_VERIFY_ATTEMPTS = 5
    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f"{self.user.username}'s Profile"

# Automatically create or update UserProfile when a User is created or updated
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)        