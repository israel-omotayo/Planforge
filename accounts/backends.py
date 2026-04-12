from django.contrib.auth.backends import ModelBackend

class VerificationAwareBackend(ModelBackend):
    def user_can_authenticate(self, user):
        # Return True so authenticate() returns unverified users 
        # instead of failing and forcing a second hash check.
        return True