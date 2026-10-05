from config.settings.base import *  # noqa: F403

DEBUG = env_bool("DJANGO_DEBUG", False)  # noqa: F405
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
# Re-read hosts after env_file injection; keep base CSRF_TRUSTED_ORIGINS (do not
# overwrite with an empty string — that previously collapsed the list to []).
_hosts = env_csv("DJANGO_ALLOWED_HOSTS")  # noqa: F405
if _hosts:
    ALLOWED_HOSTS = _hosts  # noqa: F405
_csrf = env_csv("CSRF_TRUSTED_ORIGINS")  # noqa: F405
if _csrf:
    CSRF_TRUSTED_ORIGINS = _csrf  # noqa: F405
