"""Seed a system admin AppUser and wire ASR/AI admin allowlists.

Usage:
  python manage.py seed_admin
  python manage.py seed_admin --login admin --password 'ChangeMe-admin1' --write-env

Idempotent: existing login is updated (password reset optional) and admin IDs are merged.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.passwords import hash_password
from apps.workspace.models import AppUser

DEFAULT_LOGIN = "admin"
DEFAULT_NAME = "System Admin"
DEFAULT_PASSWORD = "ChangeMe-admin1"


def _parse_id_list(raw: str | None) -> list[str]:
    return [s.strip() for s in (raw or "").split(",") if s.strip()]


def _merge_admin_ids(raw: str | None, user_id: str) -> str:
    ids = _parse_id_list(raw)
    if user_id not in ids:
        ids.append(user_id)
    return ",".join(ids)


def _upsert_env_keys(env_path: Path, updates: dict[str, str]) -> None:
    """Insert or replace KEY=value lines in a .env file."""
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        if m and m.group(1) in updates:
            key = m.group(1)
            out.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
        # Also replace commented placeholders like "# ASR_ADMIN_USER_IDS= ..."
        m2 = re.match(r"^#\s*([A-Za-z_][A-Za-z0-9_]*)=", line)
        if m2 and m2.group(1) in updates and m2.group(1) not in seen:
            key = m2.group(1)
            out.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


class Command(BaseCommand):
    help = "Seed system admin user and optionally write ASR/AI admin IDs to .env"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--login",
            default=os.environ.get("SEED_ADMIN_LOGIN", DEFAULT_LOGIN),
            help=f"Login identifier (default: {DEFAULT_LOGIN})",
        )
        parser.add_argument(
            "--display-name",
            default=os.environ.get("SEED_ADMIN_DISPLAY_NAME", DEFAULT_NAME),
            help=f"Display name (default: {DEFAULT_NAME})",
        )
        parser.add_argument(
            "--password",
            default=os.environ.get("SEED_ADMIN_PASSWORD", DEFAULT_PASSWORD),
            help="Password (min 8 chars). Prefer SEED_ADMIN_PASSWORD env in CI.",
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Force password reset when the login already exists.",
        )
        parser.add_argument(
            "--write-env",
            action="store_true",
            help="Write ASR_ADMIN_USER_IDS and AI_ADMIN_USER_IDS into .env (merge).",
        )
        parser.add_argument(
            "--env-file",
            default="",
            help="Path to .env (default: project root .env).",
        )

    def handle(self, *args, **options) -> None:
        login = (options["login"] or "").strip().lower()
        display_name = (options["display_name"] or "").strip() or DEFAULT_NAME
        password = options["password"] or ""
        if len(login) < 3:
            raise CommandError("login must be at least 3 characters")
        if len(password) < 8:
            raise CommandError("password must be at least 8 characters")

        user = AppUser.objects.filter(login_identifier=login).first()
        created = False
        if user is None:
            user = AppUser.objects.create(
                display_name=display_name,
                login_identifier=login,
                password_hash=hash_password(password),
                status=AppUser.Status.ACTIVE,
            )
            created = True
            self.stdout.write(self.style.SUCCESS(f"Created admin user {login}"))
        else:
            changed = False
            if user.display_name != display_name:
                user.display_name = display_name
                changed = True
            if user.status != AppUser.Status.ACTIVE:
                user.status = AppUser.Status.ACTIVE
                changed = True
            if options["reset_password"] or not user.password_hash:
                user.password_hash = hash_password(password)
                changed = True
                self.stdout.write(self.style.WARNING(f"Password reset for {login}"))
            if changed:
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Updated admin user {login}"))
            else:
                self.stdout.write(f"Admin user already exists: {login}")

        uid = str(user.id)
        asr_merged = _merge_admin_ids(getattr(settings, "ASR_ADMIN_USER_IDS", ""), uid)
        ai_merged = _merge_admin_ids(getattr(settings, "AI_ADMIN_USER_IDS", ""), uid)

        # Process-local so subsequent checks in this process see the admin.
        settings.ASR_ADMIN_USER_IDS = asr_merged
        settings.AI_ADMIN_USER_IDS = ai_merged

        self.stdout.write(f"user_id={uid}")
        self.stdout.write(f"ASR_ADMIN_USER_IDS={asr_merged}")
        self.stdout.write(f"AI_ADMIN_USER_IDS={ai_merged}")
        if created or options["reset_password"]:
            self.stdout.write(
                self.style.WARNING(
                    "Default password is for local/dev only — change after first login."
                )
            )

        if options["write_env"]:
            root = Path(settings.BASE_DIR)
            env_path = Path(options["env_file"]) if options["env_file"] else root / ".env"
            if not env_path.is_absolute():
                env_path = root / env_path
            # Merge with whatever is already on disk (may differ from process settings).
            existing_asr = ""
            existing_ai = ""
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("ASR_ADMIN_USER_IDS="):
                        existing_asr = line.split("=", 1)[1].strip()
                    elif line.startswith("AI_ADMIN_USER_IDS="):
                        existing_ai = line.split("=", 1)[1].strip()
            updates = {
                "ASR_ADMIN_USER_IDS": _merge_admin_ids(existing_asr, uid),
                "AI_ADMIN_USER_IDS": _merge_admin_ids(existing_ai, uid),
            }
            _upsert_env_keys(env_path, updates)
            self.stdout.write(self.style.SUCCESS(f"Wrote admin IDs to {env_path}"))
            self.stdout.write("Restart runserver/Celery to pick up .env changes.")
