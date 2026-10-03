"""AI Provider preferences + system defaults API (W8.1)."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.api_permissions import IsIdentified
from apps.core.errors import ValidationError
from apps.processing.models import SystemAiSettings, UserAiPreferences
from apps.processing.services.ai_ollama import AiProviderError, OllamaClient
from apps.processing.services.ai_resolve import (
    AI_PROVIDERS,
    require_ai_admin,
    resolve_ai_config,
    system_ai_defaults_public,
)


def _principal(request):
    return request.user


def _prefs_out(prefs: UserAiPreferences | None) -> dict:
    if prefs is None:
        return {
            "use_system_defaults": True,
            "provider": None,
            "ollama_base_url": None,
            "ollama_model": None,
            "updated_at": None,
        }
    return {
        "use_system_defaults": prefs.use_system_defaults,
        "provider": prefs.provider,
        "ollama_base_url": prefs.ollama_base_url,
        "ollama_model": prefs.ollama_model,
        "updated_at": prefs.updated_at.isoformat() if prefs.updated_at else None,
    }


def _validate_provider(value: str | None) -> str | None:
    if value is None:
        return None
    p = value.strip().lower()
    if not p:
        return None
    if p not in AI_PROVIDERS:
        raise ValidationError(
            "Unsupported AI provider",
            details={
                "fields": [
                    {
                        "field": "provider",
                        "code": "INVALID",
                        "allowed": sorted(AI_PROVIDERS),
                    }
                ]
            },
        )
    return p


@api_view(["GET", "PATCH"])
@permission_classes([IsIdentified])
def system_ai_defaults(request):
    principal = _principal(request)
    if request.method == "GET":
        return Response(system_ai_defaults_public(viewer_user_id=principal.user_id))

    require_ai_admin(principal.user_id)
    data = request.data or {}
    if data.get("reset_to_env"):
        SystemAiSettings.objects.filter(pk=1).delete()
        return Response(system_ai_defaults_public(viewer_user_id=principal.user_id))

    row, _ = SystemAiSettings.objects.get_or_create(pk=1)
    if "enabled" in data and data["enabled"] is not None:
        row.enabled = bool(data["enabled"])
    if "provider" in data:
        row.provider = _validate_provider(data.get("provider"))
    if "ollama_base_url" in data:
        raw = str(data.get("ollama_base_url") or "").strip().rstrip("/")
        row.ollama_base_url = raw or None
    if "ollama_default_model" in data:
        row.ollama_default_model = (str(data.get("ollama_default_model") or "").strip() or None)
    row.updated_by_user_id = principal.user_id
    row.updated_at = timezone.now()
    row.save()
    return Response(system_ai_defaults_public(viewer_user_id=principal.user_id))


@api_view(["GET", "PATCH"])
@permission_classes([IsIdentified])
def me_ai_preferences(request):
    principal = _principal(request)
    prefs = UserAiPreferences.objects.filter(pk=principal.user_id).first()
    if request.method == "GET":
        return Response(_prefs_out(prefs))

    data = request.data or {}
    if prefs is None:
        prefs = UserAiPreferences(user_id=principal.user_id)
    if "use_system_defaults" in data and data["use_system_defaults"] is not None:
        prefs.use_system_defaults = bool(data["use_system_defaults"])
    if "provider" in data:
        prefs.provider = _validate_provider(data.get("provider"))
    if "ollama_base_url" in data:
        raw = str(data.get("ollama_base_url") or "").strip().rstrip("/")
        prefs.ollama_base_url = raw or None
    if "ollama_model" in data:
        prefs.ollama_model = (str(data.get("ollama_model") or "").strip() or None)
    prefs.save()
    return Response(_prefs_out(prefs))


@api_view(["POST"])
@permission_classes([IsIdentified])
def me_ai_test_connection(request):
    principal = _principal(request)
    try:
        resolved = resolve_ai_config(actor_user_id=principal.user_id)
    except ValidationError as exc:
        return Response(
            {
                "ok": False,
                "provider": "ollama",
                "error": exc.message,
                "details": exc.details,
            },
            status=status.HTTP_200_OK,
        )

    if not resolved.enabled:
        return Response(
            {
                "ok": False,
                "provider": resolved.provider,
                "error": "AI provider is disabled",
                "details": {"code": "AI_PROVIDER_DISABLED"},
            }
        )

    try:
        result = OllamaClient(base_url=resolved.ollama_base_url).ping()
    except AiProviderError as exc:
        return Response(
            {
                "ok": False,
                "provider": resolved.provider,
                "error": exc.message,
                "details": {"code": exc.code},
                "base_url": resolved.ollama_base_url,
            }
        )

    models = result.get("models") or []
    model_ok = any(
        m == resolved.ollama_model or m.startswith(f"{resolved.ollama_model}:")
        for m in models
    )
    return Response(
        {
            "ok": True,
            "provider": resolved.provider,
            "model": resolved.ollama_model,
            "base_url": resolved.ollama_base_url,
            "models": models[:50],
            "model_available": model_ok or len(models) == 0,
            "message": (
                "Ollama reachable"
                + (
                    ""
                    if model_ok or not models
                    else f"; model {resolved.ollama_model!r} not in /api/tags"
                )
            ),
        }
    )
