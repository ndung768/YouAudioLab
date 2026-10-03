"""DRF authentication: Bearer JWT first; legacy X-User-Id in development/test (Gate A1)."""

from __future__ import annotations

import uuid

from django.conf import settings
from rest_framework import authentication, exceptions

from apps.core.identity import principal_from_user
from apps.core.tokens import TokenError, decode_access_token


def x_user_id_allowed() -> bool:
    explicit = getattr(settings, "AUTH_ALLOW_X_USER_ID", None)
    if explicit is not None:
        return bool(explicit)
    env = (getattr(settings, "ENVIRONMENT", "development") or "").strip().lower()
    return env in {"development", "test"}


class CompositeAuthentication(authentication.BaseAuthentication):
    """Resolve Principal from Bearer JWT, else legacy X-User-Id when allowed."""

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization") or ""
        if auth_header.strip():
            return self._from_bearer(auth_header)
        if x_user_id_allowed():
            return self._from_x_user_id(request)
        return None

    def _from_bearer(self, auth_header: str):
        parts = auth_header.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise exceptions.AuthenticationFailed(
                {
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Authorization must be Bearer <token>",
                        "details": {},
                    }
                }
            )
        try:
            user_id = decode_access_token(parts[1].strip())
        except TokenError as exc:
            raise exceptions.AuthenticationFailed(
                {
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": exc.message,
                        "details": exc.details,
                    }
                }
            ) from exc

        from apps.workspace.models import AppUser

        user = AppUser.objects.filter(id=user_id).first()
        if user is None or user.status != AppUser.Status.ACTIVE:
            raise exceptions.AuthenticationFailed(
                {
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Unknown or inactive user",
                        "details": {},
                    }
                }
            )
        return (principal_from_user(user), None)

    def _from_x_user_id(self, request):
        raw = request.headers.get("X-User-Id")
        if not raw or not raw.strip():
            return None
        try:
            user_id = uuid.UUID(raw.strip())
        except ValueError as exc:
            raise exceptions.AuthenticationFailed(
                {
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Invalid X-User-Id",
                        "details": {},
                    }
                }
            ) from exc

        from apps.workspace.models import AppUser

        user = AppUser.objects.filter(id=user_id).first()
        if user is None or user.status != AppUser.Status.ACTIVE:
            raise exceptions.AuthenticationFailed(
                {
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Unknown or inactive user",
                        "details": {},
                    }
                }
            )
        return (principal_from_user(user), None)

    def authenticate_header(self, request) -> str:
        return "Bearer"


# Back-compat alias
XUserIdAuthentication = CompositeAuthentication
