"""JWT access tokens (Gate A1) — HS256."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from django.conf import settings

from apps.core.errors import UnauthorizedError


class TokenError(UnauthorizedError):
    def __init__(self, message: str = "Invalid or expired token") -> None:
        super().__init__(message, details={"code": "TOKEN_INVALID"})


def create_access_token(*, user_id: uuid.UUID) -> str:
    import jwt

    now = datetime.now(timezone.utc)
    expire_minutes = int(getattr(settings, "JWT_EXPIRE_MINUTES", 60 * 24 * 7))
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
        "typ": "access",
    }
    return jwt.encode(
        payload,
        getattr(settings, "JWT_SECRET", "dev-only-change-me-youaudiolab-jwt"),
        algorithm=getattr(settings, "JWT_ALGORITHM", "HS256"),
    )


def decode_access_token(token: str) -> uuid.UUID:
    import jwt

    try:
        payload = jwt.decode(
            token,
            getattr(settings, "JWT_SECRET", "dev-only-change-me-youaudiolab-jwt"),
            algorithms=[getattr(settings, "JWT_ALGORITHM", "HS256")],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc

    if payload.get("typ") != "access":
        raise TokenError("Invalid token type")
    try:
        return uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError) as exc:
        raise TokenError("Invalid token subject") from exc
