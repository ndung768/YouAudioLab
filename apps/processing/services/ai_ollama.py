"""Ollama HTTP client (Gate W8.1/W8.2) — not ASR."""

from __future__ import annotations

from typing import Any

from django.conf import settings


class AiProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OllamaClient:
    def __init__(self, *, base_url: str, timeout_seconds: int | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds or int(
            getattr(settings, "AI_TIMEOUT_SECONDS", 60)
        )

    def list_tags(self) -> list[str]:
        try:
            import httpx
        except ImportError as exc:
            raise AiProviderError("AI_PROVIDER_ERROR", "httpx is not installed") from exc

        url = f"{self.base_url}/api/tags"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(url)
        except httpx.TimeoutException as exc:
            raise AiProviderError("AI_PROVIDER_TIMEOUT", f"Ollama timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise AiProviderError("AI_PROVIDER_ERROR", str(exc)[:2000]) from exc

        if resp.status_code >= 400:
            raise AiProviderError(
                "AI_PROVIDER_ERROR",
                f"Ollama HTTP {resp.status_code}: {resp.text[:500]}",
            )
        try:
            payload: dict[str, Any] = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise AiProviderError("AI_PROVIDER_ERROR", "Invalid JSON from Ollama") from exc

        models = payload.get("models") or []
        names: list[str] = []
        for m in models:
            if isinstance(m, dict) and m.get("name"):
                names.append(str(m["name"]))
        return names

    def ping(self) -> dict[str, Any]:
        names = self.list_tags()
        return {"ok": True, "models": names, "base_url": self.base_url}

    def generate(self, *, model: str, prompt: str) -> str:
        """Non-streaming /api/generate — returns response text (W8.2)."""
        try:
            import httpx
        except ImportError as exc:
            raise AiProviderError("AI_PROVIDER_ERROR", "httpx is not installed") from exc

        url = f"{self.base_url}/api/generate"
        body = {"model": model, "prompt": prompt, "stream": False}
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(url, json=body)
        except httpx.TimeoutException as exc:
            raise AiProviderError("AI_PROVIDER_TIMEOUT", f"Ollama timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise AiProviderError("AI_PROVIDER_ERROR", str(exc)[:2000]) from exc

        if resp.status_code >= 400:
            raise AiProviderError(
                "AI_PROVIDER_ERROR",
                f"Ollama HTTP {resp.status_code}: {resp.text[:1000]}",
            )
        try:
            payload: dict[str, Any] = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise AiProviderError("AI_PROVIDER_ERROR", "Invalid JSON from Ollama") from exc

        text = str(payload.get("response") or "").strip()
        if not text:
            raise AiProviderError("AI_PROVIDER_ERROR", "Empty response from Ollama")
        return text
