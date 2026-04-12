"""Notification channel providers — Twilio SMS, SendGrid email, push stubs.

Each provider is an async callable that accepts a Notification and returns
True on success. Providers gracefully degrade: when credentials are missing
or the feature flag is off, they log and return False without raising.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from app.services.notifications import Notification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SMS — Twilio
# ---------------------------------------------------------------------------

async def send_sms(notification: Notification, phone: str) -> bool:
    """Send an SMS via Twilio. Returns True on success."""
    if not settings.notifications_sms_enabled:
        logger.debug("SMS notifications disabled — skipping user %d", notification.user_id)
        return False

    if not all([settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_phone_number]):
        logger.warning("Twilio credentials not configured — cannot send SMS")
        return False

    if not phone:
        logger.warning("No phone number for user %d — cannot send SMS", notification.user_id)
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        body = f"{notification.title}\n{notification.body}"
        if len(body) > 1600:
            body = body[:1597] + "..."

        message = client.messages.create(
            body=body,
            from_=settings.twilio_phone_number,
            to=phone,
        )
        logger.info("SMS sent to user %d — SID %s", notification.user_id, message.sid)
        return True
    except ImportError:
        logger.error("twilio package not installed — run: pip install twilio")
        return False
    except Exception:
        logger.exception("Failed to send SMS to user %d", notification.user_id)
        return False


# ---------------------------------------------------------------------------
# Email — SendGrid
# ---------------------------------------------------------------------------

async def send_email(notification: Notification, email: str) -> bool:
    """Send a transactional email via SendGrid. Returns True on success."""
    if not settings.notifications_email_enabled:
        logger.debug("Email notifications disabled — skipping user %d", notification.user_id)
        return False

    if not settings.sendgrid_api_key:
        logger.warning("SendGrid API key not configured — cannot send email")
        return False

    if not email:
        logger.warning("No email for user %d — cannot send email", notification.user_id)
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Email, Content, Mail, To

        sg = SendGridAPIClient(api_key=settings.sendgrid_api_key)
        from_email = Email(settings.sendgrid_from_email, settings.sendgrid_from_name)
        to_email = To(email)
        subject = notification.title
        html_body = _build_email_html(notification)
        content = Content("text/html", html_body)
        mail = Mail(from_email, to_email, subject, content)

        response = sg.client.mail.send.post(request_body=mail.get())
        status = response.status_code
        if 200 <= status < 300:
            logger.info("Email sent to user %d — status %d", notification.user_id, status)
            return True
        else:
            logger.warning("SendGrid returned %d for user %d", status, notification.user_id)
            return False
    except ImportError:
        logger.error("sendgrid package not installed — run: pip install sendgrid")
        return False
    except Exception:
        logger.exception("Failed to send email to user %d", notification.user_id)
        return False


def _build_email_html(notification: Notification) -> str:
    """Build a simple HTML email body from a notification."""
    data_rows = ""
    if notification.data:
        items = []
        for k, v in notification.data.items():
            label = k.replace("_", " ").title()
            items.append(f"<li><strong>{label}:</strong> {v}</li>")
        if items:
            data_rows = f"<ul>{''.join(items)}</ul>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background: #6C63FF; padding: 20px; border-radius: 8px 8px 0 0;">
    <h1 style="color: white; margin: 0; font-size: 20px;">OpenRide</h1>
  </div>
  <div style="border: 1px solid #e0e0e0; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
    <h2 style="margin-top: 0;">{notification.title}</h2>
    <p>{notification.body}</p>
    {data_rows}
  </div>
  <p style="color: #999; font-size: 12px; text-align: center; margin-top: 16px;">
    You received this because you have an OpenRide account. Manage your notification preferences in the app.
  </p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Push — Firebase Cloud Messaging
# ---------------------------------------------------------------------------

# Module-level Firebase app reference (initialized lazily)
_firebase_app = None


def _get_firebase_app():
    """Return the initialized Firebase Admin app, or None if not configured."""
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    if not settings.firebase_credentials_json:
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials

        cred = credentials.Certificate(settings.firebase_credentials_json)
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized")
        return _firebase_app
    except ImportError:
        logger.error("firebase-admin package not installed — run: pip install firebase-admin")
        return None
    except Exception:
        logger.exception("Failed to initialize Firebase Admin SDK")
        return None


def _firebase_configured() -> bool:
    return bool(settings.firebase_credentials_json)


async def send_push(
    notification: Notification,
    device_tokens: list[str] | None = None,
    device_token: str | None = None,
) -> bool:
    """Send a push notification via Firebase Cloud Messaging.

    Accepts either a single ``device_token`` (legacy) or a list of
    ``device_tokens`` for multicast.

    Returns True if at least one message was accepted by FCM.
    Gracefully degrades if Firebase credentials are not configured.
    """
    if not settings.notifications_push_enabled:
        logger.debug("Push notifications disabled — skipping user %d", notification.user_id)
        return False

    # Merge single token + list
    tokens: list[str] = []
    if device_token:
        tokens.append(device_token)
    if device_tokens:
        tokens.extend(device_tokens)

    if not tokens:
        # No tokens registered — log and return (not a hard failure)
        logger.info(
            "PUSH [%s] to user %d: %s — no device tokens registered",
            notification.type.value,
            notification.user_id,
            notification.title,
        )
        return False

    if not _firebase_configured():
        logger.info(
            "PUSH [%s] to user %d: %s — Firebase not configured (skipping)",
            notification.type.value,
            notification.user_id,
            notification.title,
        )
        return False

    app = _get_firebase_app()
    if app is None:
        logger.warning("Firebase app unavailable — cannot send push to user %d", notification.user_id)
        return False

    try:
        from firebase_admin import messaging

        data_payload = {}
        if notification.data:
            # FCM data values must be strings
            data_payload = {k: str(v) for k, v in notification.data.items()}
        data_payload["notification_type"] = notification.type.value

        fcm_notification = messaging.Notification(
            title=notification.title,
            body=notification.body,
        )

        if len(tokens) == 1:
            # Single-target message
            message = messaging.Message(
                notification=fcm_notification,
                data=data_payload,
                token=tokens[0],
            )
            messaging.send(message, app=app)
            logger.info(
                "Push sent to user %d (1 token) [%s]",
                notification.user_id,
                notification.type.value,
            )
            return True
        else:
            # Multicast
            multi_message = messaging.MulticastMessage(
                notification=fcm_notification,
                data=data_payload,
                tokens=tokens,
            )
            response = messaging.send_each_for_multicast(multi_message, app=app)
            success_count = response.success_count
            failure_count = response.failure_count
            logger.info(
                "Push multicast to user %d: %d success, %d failure [%s]",
                notification.user_id,
                success_count,
                failure_count,
                notification.type.value,
            )
            return success_count > 0

    except ImportError:
        logger.error("firebase-admin package not installed")
        return False
    except Exception:
        logger.exception("Failed to send push notification to user %d", notification.user_id)
        return False
