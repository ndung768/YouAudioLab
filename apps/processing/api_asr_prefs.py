"""ASR preferences + system defaults API (W7.1–W7.3)."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.api_permissions import IsIdentified
from apps.core.errors import ForbiddenError, ValidationError
from apps.processing.models import SystemAsrSettings, UserAsrPreferences
from apps.processing.services.asr_resolve import (
    PROVIDERS,
    effective_system_asr,
    is_asr_admin,
    probe_asr_connection,
    _allowlist_local,
    _allowlist_openai,
)
from apps.processing.services.asr_secrets import decrypt_secret, encrypt_secret, mask_secret


def _principal(request):
    return request.user


def _system_defaults_out(*, editable: bool) -> dict:
    sys = effective_system_asr()
    eng = (getattr(settings, "ASR_ENGINE", "fake") or "fake").strip().lower()
    engine = "fake" if eng in {"fake", "fake-asr"} else "faster-whisper"
    return {
        "provider": sys["provider"],
        "local": {
            "engine": engine,
            "model": sys["local_model"],
            "device": sys["local_device"],
            "compute_type": sys["local_compute_type"],
            "model_allowlist": sorted(_allowlist_local()),
        },
        "openai": {
            "enabled": bool(sys["openai_enabled"]),
            "default_model": sys["openai_default_model"],
            "model_allowlist": sorted(_allowlist_openai()),
            "base_url": sys["openai_base_url"],
            "system_key_configured": bool(sys.get("openai_api_key")),
        },
        "limits": {
            "max_duration_seconds": float(getattr(settings, "ASR_MAX_DURATION_SECONDS", 1800)),
            "timeout_seconds": int(getattr(settings, "ASR_TIMEOUT_SECONDS", 600)),
        },
        "editable": editable,
        "source": sys["source"],
        "updated_at": sys["updated_at"].isoformat() if sys.get("updated_at") else None,
    }


def _prefs_out(prefs: UserAsrPreferences | None) -> dict:
    if prefs is None:
        return {
            "use_system_defaults": True,
            "provider": None,
            "local_model": None,
            "local_device": None,
            "local_compute_type": None,
            "openai_model": None,
            "openai_api_key_configured": False,
            "openai_api_key_masked": None,
            "updated_at": None,
        }
    configured = bool(prefs.openai_api_key_encrypted)
    masked = None
    if configured:
        try:
            masked = mask_secret(decrypt_secret(prefs.openai_api_key_encrypted))
        except Exception:  # noqa: BLE001
            masked = "****"
    return {
        "use_system_defaults": prefs.use_system_defaults,
        "provider": prefs.provider,
        "local_model": prefs.local_model,
        "local_device": prefs.local_device,
        "local_compute_type": prefs.local_compute_type,
        "openai_model": prefs.openai_model,
        "openai_api_key_configured": configured,
        "openai_api_key_masked": masked,
        "updated_at": prefs.updated_at.isoformat() if prefs.updated_at else None,
    }


def _validate_provider(value: str | None) -> str | None:
    if value is None:
        return None
    p = value.strip().lower()
    if not p:
        return None
    if p not in PROVIDERS:
        raise ValidationError(
            "Unsupported ASR provider",
            details={
                "fields": [
                    {"field": "provider", "code": "INVALID", "allowed": sorted(PROVIDERS)}
                ]
            },
        )
    return p


@api_view(["GET", "PATCH"])
@permission_classes([IsIdentified])
def system_asr_defaults(request):
    principal = _principal(request)
    editable = is_asr_admin(principal.user_id)
    if request.method == "GET":
        return Response(_system_defaults_out(editable=editable))

    if not editable:
        raise ForbiddenError("Only ASR admins can update system defaults")
    data = request.data or {}
    if data.get("reset_to_env"):
        SystemAsrSettings.objects.filter(pk=1).delete()
        return Response(_system_defaults_out(editable=True))

    row, _ = SystemAsrSettings.objects.get_or_create(pk=1)
    if "provider" in data:
        row.provider = _validate_provider(data.get("provider"))
    if "local_model" in data:
        lm = (data.get("local_model") or "").strip() or None
        if lm and lm not in _allowlist_local():
            raise ValidationError(
                "Unsupported local ASR model",
                details={
                    "fields": [
                        {
                            "field": "local_model",
                            "code": "INVALID",
                            "allowed": sorted(_allowlist_local()),
                        }
                    ]
                },
            )
        row.local_model = lm
    if "local_device" in data:
        row.local_device = (str(data.get("local_device") or "").strip() or None)
    if "local_compute_type" in data:
        row.local_compute_type = (str(data.get("local_compute_type") or "").strip() or None)
    if "openai_enabled" in data:
        row.openai_enabled = bool(data.get("openai_enabled"))
    if "openai_default_model" in data:
        om = (data.get("openai_default_model") or "").strip() or None
        if om and om not in _allowlist_openai():
            raise ValidationError(
                "Unsupported OpenAI ASR model",
                details={
                    "fields": [
                        {
                            "field": "openai_default_model",
                            "code": "INVALID",
                            "allowed": sorted(_allowlist_openai()),
                        }
                    ]
                },
            )
        row.openai_default_model = om
    if "openai_base_url" in data:
        row.openai_base_url = (str(data.get("openai_base_url") or "").strip() or None)
    if data.get("clear_openai_api_key"):
        row.openai_api_key_encrypted = None
    elif data.get("openai_api_key"):
        row.openai_api_key_encrypted = encrypt_secret(str(data["openai_api_key"]).strip())
    row.updated_by_user_id = principal.user_id
    row.updated_at = timezone.now()
    row.save()
    return Response(_system_defaults_out(editable=True))


@api_view(["GET", "PATCH"])
@permission_classes([IsIdentified])
def me_asr_preferences(request):
    principal = _principal(request)
    prefs = UserAsrPreferences.objects.filter(pk=principal.user_id).first()
    if request.method == "GET":
        return Response(_prefs_out(prefs))

    data = request.data or {}
    if prefs is None:
        prefs = UserAsrPreferences(user_id=principal.user_id)
    if "use_system_defaults" in data and data["use_system_defaults"] is not None:
        prefs.use_system_defaults = bool(data["use_system_defaults"])
    if "provider" in data:
        prefs.provider = _validate_provider(data.get("provider"))
    if "local_model" in data:
        lm = (data.get("local_model") or "").strip() or None
        if lm and lm not in _allowlist_local():
            raise ValidationError(
                "Unsupported local ASR model",
                details={
                    "fields": [
                        {
                            "field": "local_model",
                            "code": "INVALID",
                            "allowed": sorted(_allowlist_local()),
                        }
                    ]
                },
            )
        prefs.local_model = lm
    if "local_device" in data:
        prefs.local_device = (str(data.get("local_device") or "").strip() or None)
    if "local_compute_type" in data:
        prefs.local_compute_type = (str(data.get("local_compute_type") or "").strip() or None)
    if "openai_model" in data:
        om = (data.get("openai_model") or "").strip() or None
        if om and om not in _allowlist_openai():
            raise ValidationError(
                "Unsupported OpenAI ASR model",
                details={
                    "fields": [
                        {
                            "field": "openai_model",
                            "code": "INVALID",
                            "allowed": sorted(_allowlist_openai()),
                        }
                    ]
                },
            )
        prefs.openai_model = om
    if data.get("clear_openai_api_key"):
        prefs.openai_api_key_encrypted = None
    elif data.get("openai_api_key") is not None:
        key = str(data.get("openai_api_key") or "").strip()
        prefs.openai_api_key_encrypted = encrypt_secret(key) if key else None
    prefs.save()
    return Response(_prefs_out(prefs))


@api_view(["POST"])
@permission_classes([IsIdentified])
def me_asr_test_connection(request):
    principal = _principal(request)
    probe = probe_asr_connection(actor_user_id=principal.user_id)
    return Response(
        {
            "ok": probe.ok,
            "provider": probe.provider,
            "engine": probe.engine,
            "model": probe.model,
            "message": probe.message,
            "error": probe.error,
            "details": probe.details,
            "status": probe.status_code,
            "body": probe.body,
        }
    )
