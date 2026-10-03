# QC1 remainder: ethics fields, blind toggle, gold adjudication

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0007_project_asr_ai_defaults"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="license",
            field=models.CharField(
                blank=True,
                help_text="Corpus license, e.g. CC-BY-4.0 or research-only.",
                max_length=128,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="consent_notes",
            field=models.TextField(
                blank=True,
                help_text="Human-subjects / speaker-consent notes for this corpus.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="projectsettings",
            name="blind_annotators",
            field=models.BooleanField(
                default=True,
                help_text="When True, ANNOTATOR members cannot see peer labels.",
            ),
        ),
        migrations.CreateModel(
            name="SegmentGoldLabel",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "adjudicated_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="gold_labels_adjudicated",
                        to="workspace.appuser",
                    ),
                ),
                (
                    "label",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gold_labels",
                        to="workspace.projectlabel",
                    ),
                ),
                (
                    "segment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="gold_labels",
                        to="workspace.audiosegment",
                    ),
                ),
            ],
            options={
                "db_table": "segment_gold_labels",
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="segmentgoldlabel",
            index=models.Index(fields=["segment"], name="ix_sgl_segment_id"),
        ),
        migrations.AddConstraint(
            model_name="segmentgoldlabel",
            constraint=models.UniqueConstraint(
                fields=("segment", "label"),
                name="uq_sgl_segment_label",
            ),
        ),
    ]
