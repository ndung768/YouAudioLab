"""Point django_admin_log.user_id at workspace.AppUser (UUID PK).

When AUTH_USER_MODEL switched to AppUser, LogEntry still had an integer FK
to the leftover auth_user table. Admin index then fails with:
  operator does not exist: integer = uuid
"""

from __future__ import annotations

from django.db import migrations


FK_NAME = "django_admin_log_user_id_c564eba6_fk_auth_user_id"
NEW_FK = "django_admin_log_user_id_fk_users"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'django_admin_log'
              AND column_name = 'user_id'
            """
        )
        row = cursor.fetchone()
        if row is None or row[0] == "uuid":
            return

        cursor.execute("DELETE FROM django_admin_log")
        cursor.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'django_admin_log'::regclass
              AND contype = 'f'
              AND pg_get_constraintdef(oid) LIKE '%user_id%'
            """
        )
        for (conname,) in cursor.fetchall():
            cursor.execute(
                f'ALTER TABLE django_admin_log DROP CONSTRAINT IF EXISTS "{conname}"'
            )
        # Also drop the historical auth_user FK name if present.
        cursor.execute(
            f"ALTER TABLE django_admin_log DROP CONSTRAINT IF EXISTS {FK_NAME}"
        )
        cursor.execute(
            "ALTER TABLE django_admin_log ADD COLUMN user_id_uuid uuid NULL"
        )
        cursor.execute("ALTER TABLE django_admin_log DROP COLUMN user_id")
        cursor.execute(
            "ALTER TABLE django_admin_log RENAME COLUMN user_id_uuid TO user_id"
        )
        # Empty table: SET NOT NULL is valid.
        cursor.execute(
            "ALTER TABLE django_admin_log ALTER COLUMN user_id SET NOT NULL"
        )
        cursor.execute(
            f"""
            ALTER TABLE django_admin_log
              ADD CONSTRAINT {NEW_FK}
              FOREIGN KEY (user_id) REFERENCES users(id)
              DEFERRABLE INITIALLY DEFERRED
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS django_admin_log_user_id_idx
              ON django_admin_log (user_id)
            """
        )


def backwards(apps, schema_editor):
    # Irreversible: UUID log rows cannot map back to integer auth_user ids.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("workspace", "0013_alter_appuser_auth_help_text"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
