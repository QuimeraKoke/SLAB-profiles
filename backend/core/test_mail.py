"""Mailgun backend + the alert-email switch."""
from __future__ import annotations

from unittest import mock

from django.core.mail import EmailMultiAlternatives, get_connection
from django.test import SimpleTestCase, override_settings

MG = dict(EMAIL_BACKEND="core.mail.MailgunBackend", MAILGUN_API_KEY="k", MAILGUN_DOMAIN="s-lab.cl",
          MAILGUN_API_BASE="https://api.mailgun.net", EMAIL_REPLY_TO="contacto@s-lab.cl")


@override_settings(**MG)
class MailgunBackendTests(SimpleTestCase):
    def test_posts_the_mime_with_every_envelope_recipient(self):
        msg = EmailMultiAlternatives("Hola", "texto", "SLAB <no-reply@s-lab.cl>", ["a@x.cl"], bcc=["b@x.cl"])
        msg.attach_alternative("<p>html</p>", "text/html")
        with mock.patch("requests.post") as post:
            post.return_value.raise_for_status.return_value = None
            self.assertEqual(get_connection().send_messages([msg]), 1)
        (url,), kw = post.call_args
        self.assertEqual(url, "https://api.mailgun.net/v3/s-lab.cl/messages.mime")
        self.assertEqual(kw["auth"], ("api", "k"))
        self.assertEqual(kw["data"], [("to", "a@x.cl"), ("to", "b@x.cl")])
        mime = kw["files"]["message"][1]
        self.assertIn(b"Reply-To: contacto@s-lab.cl", mime)
        self.assertNotIn(b"b@x.cl", mime)  # bcc stays out of the headers

    def test_failure_raises_unless_silent(self):
        msg = EmailMultiAlternatives("Hola", "texto", "x@s-lab.cl", ["a@x.cl"])
        with mock.patch("requests.post", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                get_connection().send_messages([msg])
            self.assertEqual(get_connection(fail_silently=True).send_messages([msg]), 0)


class AlertEmailSwitchTests(SimpleTestCase):
    @override_settings(ALERT_EMAILS_ENABLED=False)
    def test_disabled_sends_nothing_and_touches_no_db(self):
        from goals.tasks import send_alert_email

        self.assertEqual(send_alert_email("00000000-0000-0000-0000-000000000000")["sent"], 0)
