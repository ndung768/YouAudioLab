"""Local identity adapter — session for HTML, X-User-Id for API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings
from django.http import HttpRequest

if TYPE_CHECKING:
    from apps.workspace.models import AppUser


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    login_identifier: str
    display_name: str


def get_identity_user(request: HttpRequest) -> AppUser | None:
    raw = request.session.get(settings.IDENTITY_SESSION_KEY)
    if not raw:
        return None
    try:
        user_id = uuid.UUID(str(raw))
    except ValueError:
        return None
    from apps.workspace.models import AppUser

    return AppUser.objects.filter(id=user_id, status=AppUser.Status.ACTIVE).first()


def set_identity_user(request: HttpRequest, user: AppUser) -> None:
    request.session[settings.IDENTITY_SESSION_KEY] = str(user.id)


def clear_identity(request: HttpRequest) -> None:
    request.session.pop(settings.IDENTITY_SESSION_KEY, None)


def principal_from_user(user: AppUser) -> Principal:
    return Principal(
        user_id=user.id,
        login_identifier=user.login_identifier,
        display_name=user.display_name,
    )


class IdentityMiddleware:
    """Attach request.identity_user from the HTML session (never Django auth)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        request.identity_user = get_identity_user(request)
        return self.get_response(request)
