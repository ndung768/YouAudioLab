"""DRF exception handler matching the FastAPI Gate 2 error envelope."""

from __future__ import annotations

import uuid

from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.core.errors import DomainError, ForbiddenError


def _request_id(context: dict | None) -> str:
    request = (context or {}).get("request")
    return getattr(request, "request_id", None) or str(uuid.uuid4())


def domain_exception_handler(exc, context):
    request_id = _request_id(context)

    if isinstance(exc, NotAuthenticated):
        return Response(
            {
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Missing Authorization bearer token",
                    "details": {},
                    "request_id": request_id,
                }
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, AuthenticationFailed):
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            payload = dict(detail)
            payload["error"] = dict(payload["error"])
            payload["error"].setdefault("request_id", request_id)
            return Response(payload, status=status.HTTP_401_UNAUTHORIZED)
        return Response(
            {
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": str(detail),
                    "details": {},
                    "request_id": request_id,
                }
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, DomainError):
        http_status = (
            403
            if isinstance(exc, ForbiddenError)
            else getattr(exc, "http_status", 400)
        )
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                }
            },
            status=http_status,
        )

    return exception_handler(exc, context)
