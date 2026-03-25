import logging
import threading
import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)

# Returns Json format if the request has "Accept: application/json" and does not have "text/html"
def is_json_request(request):
    accept = request.headers.get('Accept', '')
    return 'application/json' in accept and 'text/html' not in accept


def _send_via_resend(to_email: str, subject: str, html_content: str) -> None:
    """
    Send email using Resend's HTTP API.
    Faster than SMTP — no connection setup, no port 587 issues on Render.
    Raises on failure so callers can handle or log it.
    """
    api_key = getattr(settings, 'RESEND_API_KEY', '')
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not set.")

    response = requests.post(
        'https://api.resend.com/emails',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        json={
            'from': settings.DEFAULT_FROM_EMAIL,
            'to': [to_email],
            'subject': subject,
            'html': html_content,
        },
        timeout=10,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Resend API error {response.status_code}: {response.text[:200]}"
        )


def _send_via_django(to_email: str, subject: str, html_content: str) -> None:
    """
    Send email via Django's email backend (console in dev).
    Used when RESEND_API_KEY is not configured — local development only.
    """
    msg = EmailMultiAlternatives(
        subject=subject,
        body="Please view this email in an HTML-compatible client.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send(fail_silently=False)


def send_email(to_email: str, subject: str, html_content: str) -> None:
    """
    Send an email synchronously. Raises on failure so callers can handle it.

    Production (RESEND_API_KEY set): uses Resend HTTP API — no SMTP needed.
    Development (no key): falls back to Django's console email backend.

    Only use this when you need confirmation the email succeeded before continuing
    (e.g. Django's built-in password reset flow).
    For everything else use send_email_async() so the WSGI worker is not blocked.
    """
    try:
        if getattr(settings, 'RESEND_API_KEY', ''):
            _send_via_resend(to_email, subject, html_content)
        else:
            _send_via_django(to_email, subject, html_content)
        logger.info("Email sent to %s (subject=%s)", to_email, subject)
    except Exception as e:
        logger.exception("Email failed to %s: %s", to_email, e)
        raise


def send_email_async(to_email: str, subject: str, html_content: str, context: str = "") -> None:
    """
    Fire-and-forget email on a daemon thread.

    The WSGI worker returns immediately — no email latency blocks request throughout.
    The daemon flag means the thread won't prevent clean server shutdown.

    Errors are logged but NOT raised — the caller cannot await the result.
    Use this for non-critical emails where the user can request a resend
    if delivery fails (registration codes, email-change codes, invite notifications).
    """
    def _send():
        try:
            send_email(to_email, subject, html_content)
        except Exception as e:
            logger.error(
                "Async email delivery failed to %s (context=%s): %s",
                to_email, context, e,
            )

    thread = threading.Thread(target=_send, daemon=True, name=f"email-{context}")
    thread.start()