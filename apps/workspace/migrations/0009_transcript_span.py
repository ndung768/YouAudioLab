# In-transcript span labels (character offsets on the accepted transcript).

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0008_qc1_ethics_gold"),
    ]

    operations = [
        migrations.CreateModel(
            name="TranscriptSpan",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("start_char", models.PositiveIntegerField()),
                ("end_char", models.PositiveIntegerField()),
                ("quote", models.TextField()),
                ("span_group", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("transcript_sha256", models.CharField(max_length=64)),
                ("stale", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("removed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "annotator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="transcript_spans",
                        to="workspace.appuser",
                    ),
                ),
                (
                    "label",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transcript_spans",
                        to="workspace.projectlabel",
                    ),
                ),
                (
                    "removed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="removed_transcript_spans",
                        to="workspace.appuser",
                    ),
                ),
                (
                    "segment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transcript_spans",
                        to="workspace.audiosegment",
                    ),
                ),
            ],
            options={
                "db_table": "transcript_spans",
                "ordering": ["start_char", "end_char", "created_at"],
                "indexes": [
                    models.Index(fields=["segment"], name="ix_ts_segment_id"),
                    models.Index(fields=["annotator"], name="ix_ts_annotator_id"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(removed_at__isnull=True, stale=False),
                        fields=["segment", "annotator", "label", "start_char", "end_char"],
                        name="uq_ts_active",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(end_char__gt=models.F("start_char")),
                        name="ck_ts_end_gt_start",
                    ),
                ],
            },
        ),
    ]
