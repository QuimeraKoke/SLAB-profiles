"""Password lifecycle of a staff login: temporary passwords, the forced first
change, and "Olvidé mi contraseña" links.

A password someone else chose (the welcome email's, a manager's reset) is
temporary: `mark_temporary` flags the account and the app shows only the
change screen until the user picks their own (`set_own_password`).

Reset links use Django's `default_token_generator`: the token hashes the
user's current password and last login, so it dies after one use, and
`PASSWORD_RESET_TIMEOUT` caps its life at an hour. Requests never reveal
whether an email has an account; `may_send_reset` keeps one account from
being flooded.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.utils import timezone, translation
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from core.models import AccountSecurity

User = get_user_model()

# One reset email per account per this long, however often it's requested.
RESET_EMAIL_COOLDOWN = timedelta(minutes=2)


def _security(user) -> AccountSecurity:
    return AccountSecurity.objects.get_or_create(user=user)[0]


def must_change_password(user) -> bool:
    return AccountSecurity.objects.filter(user=user, must_change_password=True).exists()


def mark_temporary(user) -> None:
    AccountSecurity.objects.update_or_create(
        user=user, defaults={"must_change_password": True})


def set_own_password(user, password: str) -> None:
    """Validate and store a password the user chose. Raises Django's
    ValidationError with the validators' messages, in Spanish (the app's UI
    language; the project's LANGUAGE_CODE stays en-us)."""
    with translation.override("es"):
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            raise ValidationError([str(m) for m in exc.messages]) from None
    user.set_password(password)
    user.save(update_fields=["password"])
    AccountSecurity.objects.filter(user=user).update(must_change_password=False)


def reset_url(user) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/restablecer?uid={uid}&token={token}"


def user_for_reset(uid: str, token: str):
    """The active user a reset link belongs to, or None if it's invalid,
    used or expired."""
    try:
        pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.filter(pk=pk, is_active=True).first()
    except (TypeError, ValueError, OverflowError):
        return None
    if user is None or not default_token_generator.check_token(user, token):
        return None
    return user


def may_send_reset(user) -> bool:
    """Claim this account's reset-email slot; False while it's cooling down."""
    sec = _security(user)
    now = timezone.now()
    if sec.reset_sent_at and now - sec.reset_sent_at < RESET_EMAIL_COOLDOWN:
        return False
    sec.reset_sent_at = now
    sec.save(update_fields=["reset_sent_at"])
    return True
