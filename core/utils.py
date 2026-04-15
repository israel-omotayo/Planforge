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

def build_planforge_email(heading, message, action_content, name="there", icon_type="lock", notice="If you didn't request this, you can safely ignore this email."):
    """
    Wraps content in the high-fidelity HTML template.
    icon_type: 'lock' (for security) or 'invite' (for team/guest invites).
    """
    icons = {
        "lock": '<rect x="5" y="11" width="14" height="10" rx="2" stroke="#315C4B" stroke-width="1.75"/><path d="M8 11V7a4 4 0 0 1 8 0v4" stroke="#315C4B" stroke-width="1.75" stroke-linecap="round"/><circle cx="12" cy="16" r="1.25" fill="#315C4B"/>',
        "invite": '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" stroke="#315C4B" stroke-width="1.75"/><circle cx="8.5" cy="7" r="4" stroke="#315C4B" stroke-width="1.75"/><line x1="20" y1="8" x2="20" y2="14" stroke="#315C4B" stroke-width="1.75"/><line x1="23" y1="11" x2="17" y2="11" stroke="#315C4B" stroke-width="1.75"/>'
    }
    selected_icon = icons.get(icon_type, icons["lock"])

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <style>
        body {{ margin:0; padding:0; background:#F7F4EE; font-family:'Helvetica',Arial,sans-serif; color:#1F2933; }}
        .wrapper {{ max-width:560px; margin:0 auto; padding:2rem 1rem; }}
        .logo-text {{ font-size:1.1rem; font-weight:600; color:#1F2933; }}
        .logo-text span {{ color:#315C4B; }}
        .card {{ background:#fff; border-radius:0.875rem; border:1px solid #E7E1D8; overflow:hidden; margin-top:1.25rem; }}
        .card-body {{ padding:2rem 2rem 1.75rem; }}
        .icon-wrap {{ width:48px; height:48px; background:#EDF3F0; border-radius:12px; display:flex; align-items:center; justify-content:center; margin-bottom:1.25rem; }}
        .icon-wrap svg {{ display: block; }}
        h1 {{ margin:0 0 0.5rem; font-size:1.2rem; font-weight:600; color:#1F2933; }}
        p {{ margin:0 0 1rem; font-size:0.9rem; line-height:1.6; color:#4B5563; }}
        .action-area {{ margin:1.5rem 0; text-align: center; }}
        .btn-group {{ text-align: center; }}
        .code-box {{ 
            background:#F7F4EE; border:1px solid #E7E1D8; border-radius:0.5rem; 
            padding:1rem; font-size:1.75rem; font-weight:bold; letter-spacing:4px; 
            color:#315C4B; font-family:monospace; display:inline-block;
        }}
        .btn {{
          display:inline-block; background:#315C4B; color:#fff !important;
          text-decoration:none; padding:0.7rem 1.75rem; border-radius:0.5rem;
          font-size:0.9rem; font-weight:500;
        }}
        .secondary-link {{
            display: inline-block; margin-top: 12px; color: #9CA3AF;
            font-size: 13px; text-decoration: none; border-bottom: 1px solid #E7E1D8;
        }}
        .secondary-link:hover {{ color: #4B5563; border-bottom-color: #4B5563; }}
        .divider {{ border:none; border-top:1px solid #E7E1D8; margin:1.5rem 0; }}
        .notice {{ font-size:0.8rem; color:#9CA3AF; line-height:1.5; margin-top:1rem; }}
        .footer {{ font-size:0.75rem; color:#9CA3AF; text-align:center; line-height:1.6; margin-top:1.5rem; }}
      </style>
    </head>
    <body>
      <div class="wrapper">
        <div style="margin-bottom:0.25rem;">
          <span class="logo-text">Plan<span>forge</span></span>
        </div>
        <div class="card">
          <div class="card-body">
            <div class="icon-wrap">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                {selected_icon}
              </svg>
            </div>
            <h1>{heading}</h1>
            <p>Hi {name},</p>
            <p>{message}</p>
            <div class="action-area">
                {action_content}
            </div>
            <hr class="divider">
            <p class="notice">{notice}</p>
          </div>
        </div>
        <div class="footer">
          <p>© Planforge · This is an automated notification.</p>
        </div>
      </div>
    </body>
    </html>
    """