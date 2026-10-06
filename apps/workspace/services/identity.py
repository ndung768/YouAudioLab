"""Local user bootstrap — no passwords (auth technology OPEN)."""

from __future__ import annotations

from apps.core.errors import ConflictError, NotFoundError, ValidationError
from apps.workspace.models import AppUser
from apps.workspace.services.auth import _RESERVED_LOGINS


class IdentityService:
    def create_user(self, *, display_name: str, login_identifier: str) -> AppUser:
        login = (login_identifier or "").strip().lower()
        name = (display_name or "").strip()
        if not login or not name:
            raise ValidationError(
                "display_name and login_identifier are required",
                details={"fields": [{"field": "login_identifier", "code": "REQUIRED"}]},
            )
        if login in _RESERVED_LOGINS:
            raise ValidationError(
                "login_identifier is reserved",
                details={"fields": [{"field": "login_identifier", "code": "RESERVED"}]},
            )
        if AppUser.objects.filter(login_identifier=login).exists():
            raise ConflictError(
                "login_identifier already exists",
                details={"login_identifier": login},
            )
        return AppUser.objects.create_user(
            login_identifier=login,
            display_name=name,
            password=None,
            status=AppUser.Status.ACTIVE,
        )

    def get(self, user_id) -> AppUser:
        try:
            return AppUser.objects.get(pk=user_id)
        except AppUser.DoesNotExist as exc:
            raise NotFoundError(
                "User not found",
                details={"user_id": str(user_id)},
            ) from exc
