"""JWT auth helpers for the SLAB API.

Tokens are signed with HS256 using settings.JWT_SECRET and carry the user's
primary key plus expiry. The frontend stores the token in localStorage and
sends it via `Authorization: Bearer <token>`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from ninja.security import HttpBearer

User = get_user_model()


def issue_token(user: AbstractBaseUser) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_LIFETIME_HOURS)
    payload = {
        "sub": str(user.pk),
        "exp": int(expires_at.timestamp()),
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


class JWTAuth(HttpBearer):
    def authenticate(self, request, token: str):
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except jwt.PyJWTError:
            return None
        user = User.objects.filter(pk=payload.get("sub"), is_active=True).first()
        if user is None:
            return None
        request.user = user
        return user


jwt_auth = JWTAuth()
