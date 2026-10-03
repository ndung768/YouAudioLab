"""Auth service — register / login (Gate A1)."""

from __future__ import annotations

import re
import uuid

from apps.core.errors import ConflictError, NotFoundError, UnauthorizedError, ValidationError
from apps.core.passwords import hash_password, verify_password
from apps.core.tokens import create_access_token
from apps.workspace.models import AppUser

_LOGIN_RE = re.compile(r"^[^\s]{3,255}$")


class AuthService:
    def register(
        self,
        *,
        display_name: str,
        login_identifier: str,
        password: str,
    ) -> tuple[AppUser, str]:
        name = (display_name or "").strip()
        if not name:
            raise ValidationError(
                "display_name is required",
                details={"fields": [{"field": "display_name", "code": "REQUIRED"}]},
            )
        login = (login_identifier or "").strip().lower()
        if not _LOGIN_RE.match(login):
            raise ValidationError(
                "login_identifier must be 3–255 non-whitespace characters",
                details={"fields": [{"field": "login_identifier", "code": "INVALID"}]},
            )
        if len(password or "") < 8:
            raise ValidationError(
                "password must be at least 8 characters",
                details={"fields": [{"field": "password", "code": "TOO_SHORT"}]},
            )
        if AppUser.objects.filter(login_identifier=login).exists():
            raise ConflictError(
                "login_identifier already exists",
                details={"login_identifier": login},
            )
        user = AppUser.objects.create(
            display_name=name,
            login_identifier=login,
            password_hash=hash_password(password),
            status=AppUser.Status.ACTIVE,
        )
        return user, create_access_token(user_id=user.id)

    def login(self, *, login_identifier: str, password: str) -> tuple[AppUser, str]:
        login = (login_identifier or "").strip().lower()
        user = AppUser.objects.filter(login_identifier=login).first()
        if (
            user is None
            or user.status != AppUser.Status.ACTIVE
            or not verify_password(password, user.password_hash)
        ):
            raise UnauthorizedError("Invalid login or password")
        return user, create_access_token(user_id=user.id)

    def get_user(self, user_id: uuid.UUID) -> AppUser:
        try:
            return AppUser.objects.get(pk=user_id)
        except AppUser.DoesNotExist as exc:
            raise NotFoundError(
                "User not found",
                details={"user_id": str(user_id)},
            ) from exc
