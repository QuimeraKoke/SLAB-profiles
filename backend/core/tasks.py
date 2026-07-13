"""Celery tasks for the `core` app — staff-user lifecycle emails.

Today this is just the welcome / password-reset email fired when a manager
creates (or resets) a user from the Administración → Usuarios module. It
follows the same shape as `goals/tasks.send_alert_email`: build an
`EmailMultiAlternatives`, attach an HTML alternative, send fire-and-forget.

The one novelty vs. the alert email is inline logos: the SLAB crest and the
club crest are embedded as `cid:` images (a `multipart/related` body), which
render reliably across mail clients (external <img> URLs get blocked by
default; SVG doesn't render at all).
"""

from __future__ import annotations

import logging
from email.mime.image import MIMEImage
from pathlib import Path

from celery import shared_task

logger = logging.getLogger(__name__)

# Committed raster of frontend/public/slab-logo.svg (email clients don't
# render SVG). Read at send time; missing file just omits the logo.
SLAB_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "slab-logo.png"


def _attach_inline_image(msg, data: bytes | None, cid: str) -> bool:
    """Attach `data` as an inline image referenceable via `cid:<cid>`.
    Returns True when attached (so the HTML only references logos present)."""
    if not data:
        return False
    img = MIMEImage(data)
    img.add_header("Content-ID", f"<{cid}>")
    img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
    msg.attach(img)
    return True


def _welcome_html(*, intro, email, temp_password, login_url, club_name,
                  slab_cid, club_cid):
    """Minimal, inline-styled, table-based HTML email (client-safe)."""
    logos = ""
    if slab_cid:
        logos += (
            f'<img src="cid:{slab_cid}" alt="SLAB" '
            'style="height:44px;width:auto;vertical-align:middle" />'
        )
    if club_cid:
        if logos:
            logos += (
                '<span style="display:inline-block;width:1px;height:40px;'
                'background:#e5e7eb;margin:0 18px;vertical-align:middle"></span>'
            )
        logos += (
            f'<img src="cid:{club_cid}" alt="{club_name}" '
            'style="height:48px;width:auto;vertical-align:middle" />'
        )

    return f"""\
<div style="margin:0;padding:24px;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;color:#111827">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;
                overflow:hidden;border:1px solid #e5e7eb">
    <tr><td style="padding:28px 32px 8px;text-align:center">{logos}</td></tr>
    <tr><td style="padding:8px 32px 0">
      <h1 style="font-size:20px;margin:16px 0 4px;color:#111827">Tu cuenta en SLAB</h1>
      <p style="font-size:14px;line-height:1.5;color:#374151;margin:8px 0 20px">{intro}</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;margin:0 0 20px">
        <tr><td style="padding:14px 16px;font-size:13px;color:#6b7280">Usuario (email)</td>
            <td style="padding:14px 16px;font-size:14px;color:#111827;font-weight:bold;text-align:right">{email}</td></tr>
        <tr><td style="padding:0 16px 14px;font-size:13px;color:#6b7280">Contraseña temporal</td>
            <td style="padding:0 16px 14px;font-size:15px;color:#111827;font-weight:bold;
                       text-align:right;font-family:'Courier New',monospace">{temp_password}</td></tr>
      </table>
      <a href="{login_url}"
         style="display:inline-block;background:#111827;color:#ffffff;text-decoration:none;
                font-size:14px;font-weight:bold;padding:12px 22px;border-radius:8px">Ingresar a SLAB</a>
      <p style="font-size:12px;line-height:1.5;color:#6b7280;margin:22px 0 4px">
        Por seguridad, cambiá tu contraseña después de ingresar. Si no esperabas
        este correo, podés ignorarlo.
      </p>
    </td></tr>
    <tr><td style="padding:16px 32px 28px;border-top:1px solid #f3f4f6">
      <p style="font-size:11px;color:#9ca3af;margin:12px 0 0">SLAB · {club_name}</p>
    </td></tr>
  </table>
</div>"""


@shared_task(name="core.tasks.send_welcome_email")
def send_welcome_email(user_id, temp_password: str, reason: str = "welcome") -> dict:
    """Email a newly-created (or password-reset) user their temp password,
    with the SLAB + club logos embedded inline.

    Fire-and-forget: failures log but don't raise, so a flaky SMTP server
    never breaks the create/reset request that queued this."""
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.mail import EmailMultiAlternatives

    from core.models import StaffMembership

    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None or not user.email:
        logger.warning("send_welcome_email: user %s missing or has no email", user_id)
        return {"sent": 0}

    membership = (
        StaffMembership.objects.select_related("club").filter(user=user).first()
    )
    club = membership.club if membership else None
    club_name = club.name if club else "tu equipo"
    login_url = settings.FRONTEND_BASE_URL.rstrip("/") + "/login"

    if reason == "reset":
        subject = "SLAB — Restablecimiento de contraseña"
        intro = (
            "Se restableció tu contraseña en SLAB. Usá esta contraseña "
            "temporal para ingresar:"
        )
    else:
        subject = f"Bienvenido a SLAB — {club_name}"
        intro = (
            f"Se creó tu cuenta en SLAB para {club_name}. Usá estos datos "
            "para ingresar:"
        )

    text_body = (
        f"{intro}\n\n"
        f"Usuario (email): {user.email}\n"
        f"Contraseña temporal: {temp_password}\n\n"
        f"Ingresá en: {login_url}\n\n"
        "Por seguridad, cambiá tu contraseña después de ingresar.\n"
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    # Inline (cid) images must live in a multipart/related container.
    msg.mixed_subtype = "related"

    slab_bytes = SLAB_LOGO_PATH.read_bytes() if SLAB_LOGO_PATH.exists() else None
    slab_ok = _attach_inline_image(msg, slab_bytes, "slab_logo")

    club_ok = False
    if club is not None:
        from dashboards.pdf.scaffold import logo_image_for_club
        buf = logo_image_for_club(club)
        if buf is not None:
            club_ok = _attach_inline_image(msg, buf.getvalue(), "club_logo")

    html_body = _welcome_html(
        intro=intro,
        email=user.email,
        temp_password=temp_password,
        login_url=login_url,
        club_name=club_name,
        slab_cid="slab_logo" if slab_ok else "",
        club_cid="club_logo" if club_ok else "",
    )
    msg.attach_alternative(html_body, "text/html")

    try:
        msg.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_welcome_email failed for user %s: %s", user_id, exc)
        return {"sent": 0, "error": str(exc)}
    logger.info("send_welcome_email: %s → %s (reason=%s)", user_id, user.email, reason)
    return {"sent": 1}
