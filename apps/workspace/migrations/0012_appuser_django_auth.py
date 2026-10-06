"""Migrate AppUser to Django AUTH_USER_MODEL fields.

Copy legacy password_hash (raw bcrypt) into password as legacy_bcrypt$...,
then drop password_hash.
"""

from __future__ import annotations

import apps.workspace.models
from django.db import migrations, models


def forwards_copy_passwords(apps, schema_editor):
    AppUser = apps.get_model("workspace", "AppUser")
    for user in AppUser.objects.all().iterator():
        raw = (getattr(user, "password_hash", None) or "").strip()
        if raw:
            if raw.startswith("legacy_bcrypt$"):
                user.password = raw
            else:
                user.password = f"legacy_bcrypt${raw}"
        else:
            user.password = "!"
        user.is_active = getattr(user, "status", "ACTIVE") == "ACTIVE"
        user.save(update_fields=["password", "is_active"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("workspace", "0011_label_default_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="appuser",
            name="password",
            field=models.CharField(default="!", max_length=128, verbose_name="password"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="appuser",
            name="last_login",
            field=models.DateTimeField(blank=True, null=True, verbose_name="last login"),
        ),
        migrations.AddField(
            model_name="appuser",
            name="is_superuser",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Designates that this user has all permissions without "
                    "explicitly assigning them."
                ),
                verbose_name="superuser status",
            ),
        ),
        migrations.AddField(
            model_name="appuser",
            name="is_staff",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="appuser",
            name="is_active",
            field=models.BooleanField(
                default=True,
                help_text="Designates whether this user should be treated as active.",
                verbose_name="active",
            ),
        ),
        migrations.AddField(
            model_name="appuser",
            name="groups",
            field=models.ManyToManyField(
                blank=True,
                help_text="The groups this user belongs to.",
                related_name="user_set",
                related_query_name="user",
                to="auth.group",
                verbose_name="groups",
            ),
        ),
        migrations.AddField(
            model_name="appuser",
            name="user_permissions",
            field=models.ManyToManyField(
                blank=True,
                help_text="Specific permissions for this user.",
                related_name="user_set",
                related_query_name="user",
                to="auth.permission",
                verbose_name="user permissions",
            ),
        ),
        migrations.RunPython(forwards_copy_passwords, noop_reverse),
        migrations.RemoveField(
            model_name="appuser",
            name="password_hash",
        ),
        migrations.AlterModelManagers(
            name="appuser",
            managers=[
                ("objects", apps.workspace.models.AppUserManager()),
            ],
        ),
    ]
