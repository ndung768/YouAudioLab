"""Resolve effective ASR config: job override → user prefs → system DB/env (W7.1–W7.3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from apps.core.errors import AsrProviderMisconfiguredError, ValidationError
from apps.processing.models import SystemAsrSettings, UserAsrPreferences
from apps.processing.services.asr_secrets import decrypt_secret


PROVIDERS = {"local", "openai"}


@dataclass(frozen=True)
class ResolvedAsrConfig:
    provider: str
    engine: str
    model: str
    model_name: str
    model_size: str
    language_requested: str
    task: str
    device: str | None
    compute_type: str | None
    decode_params: dict[str, Any]
    openai_base_url: str | None
    openai_api_key: str | None
    actor_user_id: uuid.UUID
    use_system_defaults: bool
    job_override: bool


def _local_engine_name() -> str:
    eng = (getattr(settings, "ASR_ENGINE", "fake") or "fake").strip().lower()
    if eng in {"fake", "fake-asr"}:
        return "fake"
    return "faster-whisper"


def _allowlist_local() -> set[str]:
    return {
        s.strip()
        for s in (
            getattr(settings, "ASR_MODEL_ALLOWLIST", "tiny,base,small,medium,large-v3") or ""
        ).split(",")
        if s.strip()
    }


def _allowlist_openai() -> set[str]:
    raw = getattr(
        settings,
        "ASR_OPENAI_MODEL_ALLOWLIST",
        "gpt-4o-mini-transcribe,gpt-4o-transcribe,whisper-1",
    )
    return {s.strip() for s in (raw or "").split(",") if s.strip()}


def is_asr_admin(user_id: uuid.UUID) -> bool:
    ids = {
        s.strip()
        for s in (getattr(settings, "ASR_ADMIN_USER_IDS", "") or "").split(",")
        if s.strip()
    }
    if not ids:
        return (getattr(settings, "ENVIRONMENT", "development") or "").lower() == "development"
    return str(user_id) in ids


def effective_system_asr() -> dict[str, Any]:
    base = {
        "provider": (getattr(settings, "ASR_DEFAULT_PROVIDER", "local") or "local").strip().lower(),
        "local_model": (
            getattr(settings, "ASR_LOCAL_MODEL", None)
            or getattr(settings, "ASR_DEFAULT_MODEL_SIZE", "base")
            or "base"
        ).strip(),
        "local_device": getattr(settings, "ASR_DEVICE", "cpu") or "cpu",
        "local_compute_type": getattr(settings, "ASR_COMPUTE_TYPE", "int8") or "int8",
        "openai_enabled": bool(getattr(settings, "ASR_OPENAI_ENABLED", False)),
        "openai_default_model": getattr(
            settings, "ASR_OPENAI_DEFAULT_MODEL", "gpt-4o-mini-transcribe"
        )
        or "gpt-4o-mini-transcribe",
        "openai_base_url": getattr(settings, "OPENAI_BASE_URL", "https://api.openai.com/v1")
        or "https://api.openai.com/v1",
        "openai_api_key": getattr(settings, "OPENAI_API_KEY", None) or None,
        "source": "env",
        "updated_at": None,
    }
    row = SystemAsrSettings.objects.filter(pk=1).first()
    if row is None:
        return base
    if row.provider:
        base["provider"] = row.provider.strip().lower()
    if row.local_model:
        base["local_model"] = row.local_model
    if row.local_device:
        base["local_device"] = row.local_device
    if row.local_compute_type:
        base["local_compute_type"] = row.local_compute_type
    if row.openai_enabled is not None:
        base["openai_enabled"] = row.openai_enabled
    if row.openai_default_model:
        base["openai_default_model"] = row.openai_default_model
    if row.openai_base_url:
        base["openai_base_url"] = row.openai_base_url
    if row.openai_api_key_encrypted:
        try:
            base["openai_api_key"] = decrypt_secret(row.openai_api_key_encrypted)
        except ValidationError:
            pass
    base["source"] = "database"
    base["updated_at"] = row.updated_at
    return base


def resolve_asr_config(
    *,
    actor_user_id: uuid.UUID,
    language_requested: str,
    override_provider: str | None = None,
    override_model: str | None = None,
    project_id: uuid.UUID | None = None,
) -> ResolvedAsrConfig:
    """Resolve config: account/system → project protocol → job override."""
    system = effective_system_asr()
    prefs = UserAsrPreferences.objects.filter(pk=actor_user_id).first()
    use_system = prefs is None or prefs.use_system_defaults
    job_override = bool(override_provider or override_model)

    if use_system:
        provider = system["provider"]
        local_model = system["local_model"]
        device = system["local_device"]
        compute = system["local_compute_type"]
        openai_model = system["openai_default_model"]
        user_key_enc = None
    else:
        assert prefs is not None
        provider = (prefs.provider or system["provider"]).strip().lower()
        local_model = (prefs.local_model or system["local_model"]).strip()
        device = (prefs.local_device or system["local_device"]).strip()
        compute = (prefs.local_compute_type or system["local_compute_type"]).strip()
        openai_model = (prefs.openai_model or system["openai_default_model"]).strip()
        user_key_enc = prefs.openai_api_key_encrypted

    if project_id is not None:
        from apps.workspace.models import ProjectSettings

        proj = ProjectSettings.objects.filter(pk=project_id).first()
        if proj is not None and proj.asr_provider:
            provider = proj.asr_provider.strip().lower()
            if proj.asr_model:
                model_name = proj.asr_model.strip()
                if provider == "openai":
                    openai_model = model_name
                else:
                    local_model = model_name

    if override_provider:
        provider = override_provider.strip().lower()
    if override_model:
        model_override = override_model.strip()
        if provider == "openai":
            openai_model = model_override
        else:
            local_model = model_override

    if provider not in PROVIDERS:
        raise ValidationError(
            "Unsupported ASR provider",
            details={
                "fields": [
                    {
                        "field": "provider",
                        "code": "INVALID",
                        "allowed": sorted(PROVIDERS),
                    }
                ]
            },
        )

    if provider == "local":
        if local_model not in _allowlist_local():
            raise ValidationError(
                "Unsupported local ASR model",
                details={
                    "fields": [
                        {
                            "field": "model" if job_override else "local_model",
                            "code": "INVALID",
                            "allowed": sorted(_allowlist_local()),
                        }
                    ]
                },
            )
        engine = _local_engine_name()
        return ResolvedAsrConfig(
            provider="local",
            engine=engine,
            model=local_model,
            model_name=engine,
            model_size=local_model,
            language_requested=language_requested,
            task="transcribe",
            device=device,
            compute_type=compute,
            decode_params={"beam_size": 5, "vad_filter": True, "temperature": 0.0},
            openai_base_url=None,
            openai_api_key=None,
            actor_user_id=actor_user_id,
            use_system_defaults=use_system,
            job_override=job_override,
        )

    if not system["openai_enabled"]:
        raise AsrProviderMisconfiguredError(
            "OpenAI ASR provider is disabled",
            details={"code": "ASR_PROVIDER_MISCONFIGURED", "provider": "openai"},
        )
    if openai_model not in _allowlist_openai():
        raise ValidationError(
            "Unsupported OpenAI ASR model",
            details={
                "fields": [
                    {
                        "field": "model" if job_override else "openai_model",
                        "code": "INVALID",
                        "allowed": sorted(_allowlist_openai()),
                    }
                ]
            },
        )

    api_key: str | None = None
    if user_key_enc and not use_system:
        try:
            api_key = decrypt_secret(user_key_enc)
        except ValidationError:
            api_key = None
    if not api_key:
        api_key = system.get("openai_api_key")
    if not api_key:
        raise AsrProviderMisconfiguredError(
            "OpenAI API key not configured (user or system)",
            details={"code": "ASR_PROVIDER_MISCONFIGURED", "provider": "openai"},
        )

    return ResolvedAsrConfig(
        provider="openai",
        engine="openai",
        model=openai_model,
        model_name="openai",
        model_size=openai_model,
        language_requested=language_requested,
        task="transcribe",
        device=None,
        compute_type=None,
        decode_params={},
        openai_base_url=system["openai_base_url"],
        openai_api_key=api_key,
        actor_user_id=actor_user_id,
        use_system_defaults=use_system,
        job_override=job_override,
    )


def resolve_runtime_api_key(snap: dict[str, Any]) -> str | None:
    """Re-resolve OpenAI key at worker time (never stored in snapshot)."""
    if str(snap.get("provider", "local")) != "openai":
        return None
    actor_raw = snap.get("actor_user_id")
    if actor_raw:
        prefs = UserAsrPreferences.objects.filter(pk=actor_raw).first()
        if (
            prefs
            and not prefs.use_system_defaults
            and prefs.openai_api_key_encrypted
        ):
            try:
                user_key = (decrypt_secret(prefs.openai_api_key_encrypted) or "").strip()
            except ValidationError:
                user_key = ""
            if user_key:
                return user_key
    system = effective_system_asr()
    key = (system.get("openai_api_key") or "").strip() or None
    if key:
        return key
    # Distinguish “not set” vs “cannot decrypt” for clearer worker errors.
    row = SystemAsrSettings.objects.filter(pk=1).first()
    if row and row.openai_api_key_encrypted:
        from apps.processing.services.asr_secrets import secrets_key_configured

        if not secrets_key_configured():
            raise AsrProviderMisconfiguredError(
                "ASR_SECRETS_KEY missing in this process — cannot decrypt the system OpenAI key. Restart the Celery worker after setting ASR_SECRETS_KEY in .env.",
                details={"code": "ASR_SECRETS_KEY_REQUIRED", "provider": "openai"},
            )
        raise AsrProviderMisconfiguredError(
            "System OpenAI API key is stored but could not be decrypted. Check ASR_SECRETS_KEY matches the key used when saving.",
            details={"code": "ASR_SECRETS_DECRYPT_FAILED", "provider": "openai"},
        )
    raise AsrProviderMisconfiguredError(
        "OpenAI API key not configured (user or system). Set it under Settings → System ASR (or account ASR), then restart Celery if you just changed .env.",
        details={"code": "ASR_PROVIDER_MISCONFIGURED", "provider": "openai"},
    )


@dataclass(frozen=True)
class AsrConnectionProbe:
    ok: bool
    provider: str
    engine: str | None
    model: str | None
    message: str | None
    error: str | None
    status_code: int | None = None
    body: str | None = None
    details: dict[str, Any] | None = None
    key_source: str | None = None  # "user" | "system" | None


def _probe_openai_models(
    *,
    base_url: str | None,
    api_key: str,
    engine: str,
    model: str,
    key_source: str,
) -> AsrConnectionProbe:
    try:
        import httpx
    except ImportError:
        return AsrConnectionProbe(
            ok=False,
            provider="openai",
            engine=None,
            model=None,
            message=None,
            error="httpx not installed",
            key_source=key_source,
        )

    url = f"{(base_url or 'https://api.openai.com/v1').rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = int(getattr(settings, "OPENAI_TIMEOUT_SECONDS", 120))
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
    except Exception as exc:  # noqa: BLE001
        return AsrConnectionProbe(
            ok=False,
            provider="openai",
            engine=None,
            model=None,
            message=None,
            error=str(exc)[:500],
            key_source=key_source,
        )

    if resp.status_code in {401, 403}:
        return AsrConnectionProbe(
            ok=False,
            provider="openai",
            engine=None,
            model=None,
            message=(
                "OpenAI rejected the API key. "
                f"Checked {key_source} key (HTTP {resp.status_code})."
            ),
            error="ASR_AUTH_FAILED",
            status_code=resp.status_code,
            key_source=key_source,
        )
    if resp.status_code >= 400:
        return AsrConnectionProbe(
            ok=False,
            provider="openai",
            engine=None,
            model=None,
            message=None,
            error="ASR_PROVIDER_ERROR",
            status_code=resp.status_code,
            body=resp.text[:300],
            key_source=key_source,
        )
    return AsrConnectionProbe(
        ok=True,
        provider="openai",
        engine=engine,
        model=model,
        message=f"OpenAI credentials accepted ({key_source} key)",
        error=None,
        key_source=key_source,
    )


def format_asr_probe_flash(probe: AsrConnectionProbe) -> tuple[str, str]:
    """Return (level, message) for Django messages. level is success|error."""
    if probe.ok:
        detail = f" · {probe.message}" if probe.message else ""
        return (
            "success",
            f"ASR OK — {probe.provider} / {probe.engine or '—'} / {probe.model or '—'}{detail}",
        )
    if probe.error == "ASR_AUTH_FAILED":
        src = probe.key_source or "configured"
        return (
            "error",
            (
                f"OpenAI rejected the {src} API key "
                f"(HTTP {probe.status_code or 401}). "
                "Paste a valid key, or clear a bad user key under ASR → Custom."
            ),
        )
    err = probe.error or "unknown error"
    if probe.message:
        return "error", f"ASR connection failed: {err} — {probe.message}"
    return "error", f"ASR connection failed: {err}"


def probe_asr_connection(
    *,
    actor_user_id: uuid.UUID,
    system_only: bool = False,
) -> AsrConnectionProbe:
    """Live OpenAI /models check. system_only ignores user custom prefs (admin test)."""
    if system_only:
        system = effective_system_asr()
        provider = (system.get("provider") or "local").strip().lower()
        if provider != "openai":
            engine = _local_engine_name()
            return AsrConnectionProbe(
                ok=True,
                provider="local",
                engine=engine,
                model=system.get("local_model"),
                message="System default provider is local; no remote connection test needed",
                error=None,
                key_source="system",
            )
        if not system.get("openai_enabled"):
            return AsrConnectionProbe(
                ok=False,
                provider="openai",
                engine=None,
                model=None,
                message=None,
                error="OpenAI ASR provider is disabled in system defaults",
                key_source="system",
            )
        api_key = system.get("openai_api_key")
        if not api_key:
            return AsrConnectionProbe(
                ok=False,
                provider="openai",
                engine=None,
                model=None,
                message=None,
                error="System OpenAI API key is not configured",
                key_source="system",
            )
        return _probe_openai_models(
            base_url=system.get("openai_base_url"),
            api_key=api_key,
            engine="openai",
            model=system.get("openai_default_model") or "gpt-4o-mini-transcribe",
            key_source="system",
        )

    try:
        resolved = resolve_asr_config(
            actor_user_id=actor_user_id,
            language_requested="en",
        )
    except ValidationError as exc:
        return AsrConnectionProbe(
            ok=False,
            provider="openai",
            engine=None,
            model=None,
            message=None,
            error=exc.message,
            details=exc.details,
        )
    except AsrProviderMisconfiguredError as exc:
        return AsrConnectionProbe(
            ok=False,
            provider="openai",
            engine=None,
            model=None,
            message=None,
            error=exc.message,
            details=getattr(exc, "details", None),
        )

    if resolved.provider != "openai":
        return AsrConnectionProbe(
            ok=True,
            provider=resolved.provider,
            engine=resolved.engine,
            model=resolved.model,
            message="Local provider selected; no remote connection test needed",
            error=None,
        )

    prefs = UserAsrPreferences.objects.filter(pk=actor_user_id).first()
    key_source = "system"
    if (
        prefs
        and not prefs.use_system_defaults
        and prefs.openai_api_key_encrypted
    ):
        key_source = "user"

    return _probe_openai_models(
        base_url=resolved.openai_base_url,
        api_key=resolved.openai_api_key or "",
        engine=resolved.engine,
        model=resolved.model,
        key_source=key_source,
    )
