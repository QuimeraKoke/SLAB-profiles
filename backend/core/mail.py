"""Mailgun email backend (HTTP API, no SMTP credentials needed).

Sends each message through `POST /v3/<domain>/messages.mime` with the MIME
Django already built, so everything the messages carry — the HTML
alternative, the inline CID logos of the welcome email — goes out byte for
byte, and the envelope recipients (to + cc + bcc) are passed explicitly.

Selected automatically when `MAILGUN_API_KEY` is set (config/settings.py).
The domain `s-lab.cl` lives in Mailgun's US region: `MAILGUN_API_BASE`
defaults to https://api.mailgun.net.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

TIMEOUT = 20  # seconds


class MailgunBackend(BaseEmailBackend):
    def send_messages(self, email_messages) -> int:
        import requests

        sent = 0
        url = f"{settings.MAILGUN_API_BASE.rstrip('/')}/v3/{settings.MAILGUN_DOMAIN}/messages.mime"
        for message in email_messages or []:
            recipients = message.recipients()
            if not recipients:
                continue
            if not message.reply_to and getattr(settings, "EMAIL_REPLY_TO", ""):
                message.reply_to = [settings.EMAIL_REPLY_TO]
            try:
                r = requests.post(
                    url, auth=("api", settings.MAILGUN_API_KEY),
                    data=[("to", rcpt) for rcpt in recipients],
                    files={"message": ("message.mime", message.message().as_bytes())},
                    timeout=TIMEOUT,
                )
                r.raise_for_status()
                sent += 1
            except Exception as exc:  # noqa: BLE001
                # Never log the response body: Mailgun may echo request data.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                logger.warning("mailgun send failed (%s): %s", status, type(exc).__name__)
                if not self.fail_silently:
                    raise
        return sent
