from config.settings.base import *  # noqa: F403

DEBUG = env_bool("DJANGO_DEBUG", False)  # noqa: F405
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
ALLOWED_HOSTS = [
    host.strip()
    for host in (env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,web") or "").split(",")  # noqa: F405
    if host.strip()
]
_csrf = env("CSRF_TRUSTED_ORIGINS")  # noqa: F405
if _csrf is not None:
    CSRF_TRUSTED_ORIGINS = [  # noqa: F405
        origin.strip().rstrip("/")
        for origin in _csrf.split(",")
        if origin.strip()
    ]
