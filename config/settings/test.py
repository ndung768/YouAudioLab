import os

from config.settings.base import *  # noqa: F403
from config.settings.base import parse_database_url

ENVIRONMENT = "test"
DEBUG = True
CELERY_ENQUEUE_ENABLED = False
CELERY_TASK_ALWAYS_EAGER = False
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
    "apps.core.hashers.LegacyBcryptPasswordHasher",
]

if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": parse_database_url(os.environ["DATABASE_URL"])}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
