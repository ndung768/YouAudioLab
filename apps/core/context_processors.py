from __future__ import annotations

from django.http import HttpRequest


def identity(request: HttpRequest) -> dict:
    user = getattr(request, "identity_user", None)
    return {
        "identity_user": user,
        "is_identified": user is not None,
    }
