from django.core.mail import send_mail
from django.conf import settings
from django.utils.crypto import get_random_string

def generate_verification_token():
    """Generate a random verification token."""
    return get_random_string(64)

def send_verification_email(user_email, verification_token):
    """Send email verification link to user."""
    verification_link = f"{settings.FRONTEND_URL}/verify-email/{verification_token}/"
    subject = 'Email Verification - DocEvalKapiyu'
    message = f'Please click the link to verify your email: {verification_link}'

    try:
        send_mail(
            subject,
            message,
            settings.EMAIL_HOST_USER,
            [user_email],
            fail_silently=False,
        )
    except Exception as e:
        # Log the error appropriately
        print(f"Failed to send verification email to {user_email}: {e}")
        # In production, use logging instead of print
        # logger.error(f"Failed to send verification email to {user_email}: {e}")