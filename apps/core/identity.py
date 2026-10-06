"""Identity adapter — Django session auth for HTML; JWT/X-User-Id for API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.http import HttpRequest

if TYPE_CHECKING:
    from apps.workspace.models import AppUser


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    login_identifier: str
    display_name: str


def get_identity_user(request: HttpRequest) -> AppUser | None:
    from apps.workspace.models import AppUser

    user = getattr(request, "user", None)
    if (
        user is not None
        and getattr(user, "is_authenticated", False)
        and isinstance(user, AppUser)
        and user.status == AppUser.Status.ACTIVE
        and user.is_active
    ):
        return user

    # Legacy session bridge (pre-AUTH_USER_MODEL HTML sessions).
    raw = request.session.get(settings.IDENTITY_SESSION_KEY)
    if not raw:
        return None
    try:
        user_id = uuid.UUID(str(raw))
    except ValueError:
        return None
    return AppUser.objects.filter(
        id=user_id,
        status=AppUser.Status.ACTIVE,
        is_active=True,
    ).first()


def set_identity_user(request: HttpRequest, user: AppUser) -> None:
    """Establish Django session auth and keep legacy session key for templates."""
    django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session[settings.IDENTITY_SESSION_KEY] = str(user.id)


def clear_identity(request: HttpRequest) -> None:
    django_logout(request)
    request.session.pop(settings.IDENTITY_SESSION_KEY, None)


def principal_from_user(user: AppUser) -> Principal:
    return Principal(
        user_id=user.id,
        login_identifier=user.login_identifier,
        display_name=user.display_name,
    )


class IdentityMiddleware:
    """Attach request.identity_user from Django auth (legacy session fallback)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        request.identity_user = get_identity_user(request)
        return self.get_response(request)
