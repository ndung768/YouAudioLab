"""AI Provider resolve — Ollama prefs (Gate W8.1). Never touches ASR."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from apps.core.errors import ForbiddenError, ValidationError
from apps.processing.models import SystemAiSettings, UserAiPreferences

AI_PROVIDERS = frozenset({"ollama"})


@dataclass(frozen=True)
class ResolvedAiConfig:
    enabled: bool
    provider: str
    ollama_base_url: str
    ollama_model: str
    actor_user_id: uuid.UUID
    use_system_defaults: bool


def is_ai_admin(user_id: uuid.UUID) -> bool:
    ids = {
        s.strip()
        for s in (getattr(settings, "AI_ADMIN_USER_IDS", "") or "").split(",")
        if s.strip()
    }
    if ids:
        return str(user_id) in ids
    return (getattr(settings, "ENVIRONMENT", "development") or "").lower() == "development"


def require_ai_admin(user_id: uuid.UUID) -> None:
    if not is_ai_admin(user_id):
        raise ForbiddenError(
            "AI system defaults require admin privileges",
            details={"code": "AI_ADMIN_REQUIRED"},
        )


def effective_system_ai() -> dict[str, Any]:
    base = {
        "enabled": bool(getattr(settings, "AI_ENABLED", False)),
        "provider": (getattr(settings, "AI_DEFAULT_PROVIDER", "ollama") or "ollama")
        .strip()
        .lower(),
        "ollama_base_url": (
            getattr(settings, "AI_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
            or "http://127.0.0.1:11434"
        ).rstrip("/"),
        "ollama_default_model": (
            getattr(settings, "AI_OLLAMA_DEFAULT_MODEL", "llama3.2") or "llama3.2"
        ).strip(),
        "source": "env",
        "updated_at": None,
    }
    row = SystemAiSettings.objects.filter(pk=1).first()
    if row is None:
        return base
    if row.enabled is not None:
        base["enabled"] = bool(row.enabled)
    if row.provider:
        base["provider"] = row.provider.strip().lower()
    if row.ollama_base_url:
        base["ollama_base_url"] = row.ollama_base_url.strip().rstrip("/")
    if row.ollama_default_model:
        base["ollama_default_model"] = row.ollama_default_model.strip()
    base["source"] = "database"
    base["updated_at"] = row.updated_at
    return base


def system_ai_defaults_public(*, viewer_user_id: uuid.UUID | None = None) -> dict[str, Any]:
    eff = effective_system_ai()
    return {
        "enabled": eff["enabled"],
        "provider": eff["provider"],
        "ollama": {
            "base_url": eff["ollama_base_url"],
            "default_model": eff["ollama_default_model"],
        },
        "limits": {
            "timeout_seconds": int(getattr(settings, "AI_TIMEOUT_SECONDS", 60)),
        },
        "editable": bool(viewer_user_id and is_ai_admin(viewer_user_id)),
        "source": eff["source"],
        "updated_at": eff["updated_at"].isoformat() if eff.get("updated_at") else None,
    }


def resolve_ai_config(
    *,
    actor_user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
) -> ResolvedAiConfig:
    eff = effective_system_ai()
    prefs = UserAiPreferences.objects.filter(pk=actor_user_id).first()
    use_system = prefs is None or prefs.use_system_defaults

    if use_system:
        provider = eff["provider"]
        base_url = eff["ollama_base_url"]
        model = eff["ollama_default_model"]
    else:
        assert prefs is not None
        provider = (prefs.provider or eff["provider"]).strip().lower()
        base_url = (prefs.ollama_base_url or eff["ollama_base_url"]).strip().rstrip("/")
        model = (prefs.ollama_model or eff["ollama_default_model"]).strip()

    enabled = bool(eff["enabled"])
    if project_id is not None:
        from apps.workspace.models import ProjectSettings

        proj = ProjectSettings.objects.filter(pk=project_id).first()
        if proj is not None:
            if proj.ai_enabled is not None:
                enabled = bool(proj.ai_enabled)
            if proj.ai_provider:
                provider = proj.ai_provider.strip().lower()
            if proj.ai_ollama_base_url:
                base_url = proj.ai_ollama_base_url.strip().rstrip("/")
            if proj.ai_ollama_model:
                model = proj.ai_ollama_model.strip()

    if provider not in AI_PROVIDERS:
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

    return ResolvedAiConfig(
        enabled=enabled,
        provider=provider,
        ollama_base_url=base_url,
        ollama_model=model,
        actor_user_id=actor_user_id,
        use_system_defaults=use_system,
    )
