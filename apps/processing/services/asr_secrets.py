"""Encrypt/decrypt per-user / system ASR secrets (Gate W7.1)."""

from __future__ import annotations

import base64
import hashlib

from django.conf import settings

from apps.core.errors import ValidationError


def _fernet():
    raw = (getattr(settings, "ASR_SECRETS_KEY", None) or "").strip()
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise ValidationError(
            "cryptography package required for per-user ASR secrets",
            details={"fields": [{"field": "openai_api_key", "code": "UNAVAILABLE"}]},
        ) from exc
    try:
        return Fernet(raw.encode("utf-8"))
    except Exception:
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        from cryptography.fernet import Fernet

        return Fernet(base64.urlsafe_b64encode(digest))


def secrets_key_configured() -> bool:
    return _fernet() is not None


def encrypt_secret(plaintext: str) -> str:
    f = _fernet()
    if f is None:
        raise ValidationError(
            "ASR_SECRETS_KEY is not configured; cannot store per-user API keys",
            details={"fields": [{"field": "openai_api_key", "code": "SECRETS_KEY_REQUIRED"}]},
        )
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    f = _fernet()
    if f is None:
        raise ValidationError(
            "ASR_SECRETS_KEY is not configured; cannot read per-user API keys",
            details={"fields": [{"field": "openai_api_key", "code": "SECRETS_KEY_REQUIRED"}]},
        )
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        raise ValidationError(
            "Failed to decrypt stored API key",
            details={"fields": [{"field": "openai_api_key", "code": "DECRYPT_FAILED"}]},
        ) from exc


def mask_secret(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    if len(plaintext) <= 4:
        return "****"
    return f"...{plaintext[-4:]}"
