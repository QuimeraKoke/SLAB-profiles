"""Builds the real "Recuperar contraseña" email for the demo user, without
sending it, and prints it as JSON (subject, sender, HTML with the logos
inlined, and the reset link). Run inside the local backend container:

    docker compose exec -T backend python manage.py shell < tutoriales/recuperar-contrasena/exportar_correo.py

The link is valid until the demo user's password changes, so export it right
before recording.
"""
import base64
import json

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test.utils import override_settings

from core.tasks import send_password_reset_email

EMAIL = "demo@laroja.cl"
FRONT = "http://localhost:3001"

user = get_user_model().objects.get(email__iexact=EMAIL)
# Re-recording asks for a link several times an hour: clear the throttles.
try:
    cache.delete_pattern("forgot-password:*")
except AttributeError:
    cache.clear()

with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                       FRONTEND_BASE_URL=FRONT):
    mail.outbox = []
    send_password_reset_email(user.pk)
    msg = mail.outbox[0]

html = next(c for c, mime in msg.alternatives if mime == "text/html")
for att in msg.attachments:
    cid = (att.get("Content-ID") or "").strip("<>") if hasattr(att, "get") else ""
    if cid:
        data = base64.b64encode(att.get_payload(decode=True)).decode()
        html = html.replace(f"cid:{cid}", f"data:{att.get_content_type()};base64,{data}")

url = html.split('href="', 1)[1].split('"', 1)[0]
print("@@CORREO@@" + json.dumps({
    "asunto": msg.subject,
    "de": "SLAB <no-reply@s-lab.cl>",  # prod sender (local uses a placeholder)
    "para": EMAIL,
    "html": html,
    "url": url,
}))
