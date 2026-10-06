"""Shared Django settings for YouAudioLab_Django."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse, unquote

BASE_DIR = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE from .env into os.environ (does not override existing)."""
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    return value


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def env_csv(name: str, default: str = "") -> list[str]:
    """Comma-separated env list; empty/whitespace items dropped; trailing / stripped."""
    raw = env(name)
    if raw is None or not str(raw).strip():
        raw = default
    return [part.strip().rstrip("/") for part in str(raw).split(",") if part.strip()]


def parse_database_url(url: str) -> dict:
    """Accept postgresql:// and postgresql+psycopg:// URLs."""
    normalized = url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or 5432),
    }


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_csv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_csv(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:8001,http://127.0.0.1:8001",
)
# Behind nginx/Caddy TLS termination: trust X-Forwarded-Proto for HTTPS detection.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

AUTH_USER_MODEL = "workspace.AppUser"
LOGIN_URL = "/identity/"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "apps.core.hashers.LegacyBcryptPasswordHasher",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.workspace",
    "apps.processing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "apps.core.identity.IdentityMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.identity",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

_DEFAULT_DB = "postgresql://youaudiolab:youaudiolab@localhost:5433/youaudiolab_django"
DATABASES = {
    "default": parse_database_url(env("DATABASE_URL", _DEFAULT_DB) or _DEFAULT_DB),
}

LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", "English"),
    ("vi", "Tiếng Việt"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Bootstrap-compatible message tags (Django "error" → alert-danger)
from django.contrib.messages import constants as message_constants  # noqa: E402

MESSAGE_TAGS = {
    message_constants.DEBUG: "secondary",
    message_constants.INFO: "info",
    message_constants.SUCCESS: "success",
    message_constants.WARNING: "warning",
    message_constants.ERROR: "danger",
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.core.api_auth.CompositeAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "EXCEPTION_HANDLER": "apps.core.api_errors.domain_exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "UNAUTHENTICATED_USER": None,
}

# Operational configuration (not Django settings secrets)
ENVIRONMENT = env("ENVIRONMENT", "development") or "development"
STORAGE_ROOT = env("STORAGE_ROOT", str(BASE_DIR / "storage")) or str(BASE_DIR / "storage")
REDIS_URL = env("REDIS_URL", "redis://localhost:6381/0") or "redis://localhost:6381/0"
CELERY_BROKER_URL = env("CELERY_BROKER_URL") or REDIS_URL
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND") or REDIS_URL
CELERY_WORKER_CONCURRENCY = env_int("CELERY_WORKER_CONCURRENCY", 2)
CELERY_ENQUEUE_ENABLED = env_bool("CELERY_ENQUEUE_ENABLED", True)
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = "UTC"
CELERY_ENABLE_UTC = True
FFMPEG_BIN = env("FFMPEG_BIN", "ffmpeg") or "ffmpeg"
YTDLP_COOKIES_FILE = env("YTDLP_COOKIES_FILE")
FFMPEG_TIMEOUT_SECONDS = env_int("FFMPEG_TIMEOUT_SECONDS", 300)
YTDLP_SOCKET_TIMEOUT = env_int("YTDLP_SOCKET_TIMEOUT", 30)
IDEMPOTENCY_RETENTION_HOURS = env_int("IDEMPOTENCY_RETENTION_HOURS", 72)

# Gate A1 — JWT + password
JWT_SECRET = env("JWT_SECRET", "dev-only-change-me-youaudiolab-jwt") or "dev-only-change-me-youaudiolab-jwt"
JWT_ALGORITHM = env("JWT_ALGORITHM", "HS256") or "HS256"
JWT_EXPIRE_MINUTES = env_int("JWT_EXPIRE_MINUTES", 60 * 24 * 7)
_auth_x = env("AUTH_ALLOW_X_USER_ID")
AUTH_ALLOW_X_USER_ID = None if _auth_x is None else env_bool("AUTH_ALLOW_X_USER_ID", False)

# Phase 2 ASR (W2–W5 + W7 providers/prefs)
ASR_ENGINE = env("ASR_ENGINE", "fake") or "fake"
ASR_DEFAULT_PROVIDER = env("ASR_DEFAULT_PROVIDER", "local") or "local"
ASR_DEFAULT_MODEL_SIZE = env("ASR_DEFAULT_MODEL_SIZE", "base") or "base"
ASR_LOCAL_MODEL = env("ASR_LOCAL_MODEL") or ASR_DEFAULT_MODEL_SIZE
ASR_MODEL_ALLOWLIST = env(
    "ASR_MODEL_ALLOWLIST", "tiny,base,small,medium,large-v3"
) or "tiny,base,small,medium,large-v3"
ASR_DEVICE = env("ASR_DEVICE", "cpu") or "cpu"
ASR_COMPUTE_TYPE = env("ASR_COMPUTE_TYPE", "int8") or "int8"
ASR_MAX_DURATION_SECONDS = env_int("ASR_MAX_DURATION_SECONDS", 1800)
ASR_TIMEOUT_SECONDS = env_int("ASR_TIMEOUT_SECONDS", 600)
ASR_MODEL_CACHE_DIR = env(
    "ASR_MODEL_CACHE_DIR", str(BASE_DIR / "storage" / "whisper-models")
) or str(BASE_DIR / "storage" / "whisper-models")
ASR_DOWNLOAD_MODELS = env_bool("ASR_DOWNLOAD_MODELS", True)
ASR_OPENAI_ENABLED = env_bool("ASR_OPENAI_ENABLED", False)
ASR_OPENAI_DEFAULT_MODEL = (
    env("ASR_OPENAI_DEFAULT_MODEL", "gpt-4o-mini-transcribe") or "gpt-4o-mini-transcribe"
)
ASR_OPENAI_MODEL_ALLOWLIST = env(
    "ASR_OPENAI_MODEL_ALLOWLIST",
    "gpt-4o-mini-transcribe,gpt-4o-transcribe,whisper-1",
) or "gpt-4o-mini-transcribe,gpt-4o-transcribe,whisper-1"
OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", "https://api.openai.com/v1") or "https://api.openai.com/v1"
OPENAI_TIMEOUT_SECONDS = env_int("OPENAI_TIMEOUT_SECONDS", 120)
ASR_SECRETS_KEY = (env("ASR_SECRETS_KEY") or "").strip() or None
# Dev/test convenience: encrypt per-user keys with Django SECRET_KEY when unset.
if not ASR_SECRETS_KEY and ENVIRONMENT in {"development", "test"}:
    ASR_SECRETS_KEY = SECRET_KEY
ASR_ADMIN_USER_IDS = env("ASR_ADMIN_USER_IDS", "") or ""

# Phase 2 AI Provider (W8.1–W8.3) — separate from ASR
AI_ENABLED = env_bool("AI_ENABLED", False)
AI_DEFAULT_PROVIDER = env("AI_DEFAULT_PROVIDER", "ollama") or "ollama"
AI_OLLAMA_BASE_URL = (
    env("AI_OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "http://127.0.0.1:11434"
)
AI_OLLAMA_DEFAULT_MODEL = env("AI_OLLAMA_DEFAULT_MODEL", "llama3.2") or "llama3.2"
AI_TIMEOUT_SECONDS = env_int("AI_TIMEOUT_SECONDS", 60)
AI_ADMIN_USER_IDS = env("AI_ADMIN_USER_IDS", "") or ""

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

IDENTITY_SESSION_KEY = "identity_user_id"
