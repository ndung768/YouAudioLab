"""ASR engine port — Fake (W3) + optional FasterWhisper (W4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class AsrEngineResult:
    text: str
    language_detected: str | None = None
    segments_json: list[dict[str, Any]] | None = None
    words_json: list[dict[str, Any]] | None = None
    confidence_summary: dict[str, Any] | None = None
    model_version: str | None = None
    model_path_or_id: str | None = None


@dataclass(frozen=True)
class AsrEngineConfig:
    model_name: str = "faster-whisper"
    model_size: str = "base"
    language_requested: str = "vi"
    task: str = "transcribe"
    device: str = "cpu"
    compute_type: str = "int8"
    decode_params: dict[str, Any] = field(
        default_factory=lambda: {
            "beam_size": 5,
            "vad_filter": True,
            "temperature": 0.0,
        }
    )
    provider: str = "local"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_timeout_seconds: int = 120


class AsrEngine(Protocol):
    def transcribe(self, audio_bytes: bytes, config: AsrEngineConfig) -> AsrEngineResult:
        ...


class AsrEngineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FakeAsrEngine:
    def __init__(self, *, text: str = "fake transcript", language: str | None = "vi") -> None:
        self._text = text
        self._language = language

    def transcribe(self, audio_bytes: bytes, config: AsrEngineConfig) -> AsrEngineResult:
        _ = len(audio_bytes)
        detected = None if config.language_requested == "auto" else config.language_requested
        if self._language is not None:
            detected = self._language
        return AsrEngineResult(
            text=self._text,
            language_detected=detected,
            model_version="fake-0",
            model_path_or_id="fake://model",
        )


class FasterWhisperEngine:
    def __init__(self, *, model_cache_dir: str | Path, download: bool = True) -> None:
        self.model_cache_dir = Path(model_cache_dir)
        self.download = download
        self._models: dict[tuple[str, str, str], Any] = {}

    def _load_model(self, config: AsrEngineConfig) -> Any:
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        except ImportError as exc:
            raise AsrEngineError(
                "MODEL_UNAVAILABLE",
                "faster-whisper is not installed",
            ) from exc
        key = (config.model_size, config.device, config.compute_type)
        if key in self._models:
            return self._models[key]
        self.model_cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            model = WhisperModel(
                config.model_size,
                device=config.device,
                compute_type=config.compute_type,
                download_root=str(self.model_cache_dir),
                local_files_only=not self.download,
            )
        except Exception as exc:  # noqa: BLE001
            code = "MODEL_DOWNLOAD_FAILED" if self.download else "MODEL_UNAVAILABLE"
            raise AsrEngineError(code, str(exc)[:2000]) from exc
        self._models[key] = model
        return model

    def transcribe(self, audio_bytes: bytes, config: AsrEngineConfig) -> AsrEngineResult:
        import tempfile

        model = self._load_model(config)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            lang = None if config.language_requested == "auto" else config.language_requested
            decode = config.decode_params or {}
            segments_iter, info = model.transcribe(
                tmp.name,
                language=lang,
                task=config.task,
                beam_size=int(decode.get("beam_size", 5)),
                vad_filter=bool(decode.get("vad_filter", True)),
                temperature=float(decode.get("temperature", 0.0)),
            )
            parts: list[str] = []
            for seg in segments_iter:
                parts.append(seg.text.strip())
            text = " ".join(p for p in parts if p).strip()
            detected = getattr(info, "language", None)
        return AsrEngineResult(
            text=text,
            language_detected=detected,
            model_version="faster-whisper",
            model_path_or_id=config.model_size,
        )


class OpenAITranscriptionEngine:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 120,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout

    def transcribe(self, audio_bytes: bytes, config: AsrEngineConfig) -> AsrEngineResult:
        if not self.api_key:
            raise AsrEngineError("ASR_AUTH_FAILED", "OpenAI API key missing")
        try:
            import httpx
        except ImportError as exc:
            raise AsrEngineError("ASR_PROVIDER_ERROR", "httpx is not installed") from exc

        url = f"{self.base_url}/audio/transcriptions"
        data: dict[str, str] = {"model": config.model_size}
        if config.language_requested and config.language_requested != "auto":
            data["language"] = config.language_requested
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, data=data, files=files)
        except httpx.TimeoutException as exc:
            raise AsrEngineError("ASR_PROVIDER_ERROR", "OpenAI request timed out") from exc
        except Exception as exc:  # noqa: BLE001
            raise AsrEngineError("ASR_PROVIDER_ERROR", str(exc)[:2000]) from exc

        if response.status_code in {401, 403}:
            raise AsrEngineError("ASR_AUTH_FAILED", response.text[:500])
        if response.status_code == 429:
            raise AsrEngineError("ASR_QUOTA", response.text[:500])
        if response.status_code >= 400:
            raise AsrEngineError("ASR_PROVIDER_ERROR", response.text[:500])
        payload = response.json()
        text = str(payload.get("text") or "")
        return AsrEngineResult(
            text=text,
            language_detected=payload.get("language"),
            model_version=f"openai:{config.model_size}",
            model_path_or_id=f"openai:{config.model_size}",
        )


def build_asr_engine(
    *,
    engine_name: str | None = None,
    model_cache_dir: str = "./storage/whisper-models",
    download: bool = True,
    provider: str = "local",
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    openai_timeout_seconds: int = 120,
) -> AsrEngine:
    if (provider or "local").strip().lower() == "openai":
        return OpenAITranscriptionEngine(
            api_key=openai_api_key or "",
            base_url=openai_base_url or "https://api.openai.com/v1",
            timeout=openai_timeout_seconds,
        )
    name = (engine_name or "fake").strip().lower()
    if name == "fake":
        return FakeAsrEngine()
    if name in {"faster-whisper", "faster_whisper"}:
        return FasterWhisperEngine(model_cache_dir=model_cache_dir, download=download)
    return FakeAsrEngine()
