"""Migrate project-scoped LabelDefinition → AnnotaHub Label + ProjectLabel."""

from __future__ import annotations

import uuid

from django.db import migrations, models
import django.db.models.deletion
from django.db.models.functions import Lower


def forwards_migrate_labels(apps, schema_editor):
    LabelDefinition = apps.get_model("workspace", "LabelDefinition")
    Label = apps.get_model("workspace", "Label")
    ProjectLabel = apps.get_model("workspace", "ProjectLabel")
    ProjectMembership = apps.get_model("workspace", "ProjectMembership")
    SegmentAnnotation = apps.get_model("workspace", "SegmentAnnotation")

    ld_to_pl: dict[uuid.UUID, uuid.UUID] = {}

    for ld in LabelDefinition.objects.all().order_by("created_at"):
        owner_membership = (
            ProjectMembership.objects.filter(
                project_id=ld.project_id,
                role="OWNER",
                revoked_at__isnull=True,
            )
            .order_by("created_at")
            .first()
        )
        if owner_membership is None:
            continue
        owner_id = owner_membership.user_id

        name_key = (ld.name or "").strip().lower()
        label = (
            Label.objects.filter(owner_id=owner_id)
            .annotate(name_lower=Lower("name"))
            .filter(name_lower=name_key)
            .first()
        )
        if label is None:
            label = Label.objects.create(
                id=uuid.uuid4(),
                owner_id=owner_id,
                name=ld.name,
                description=ld.description,
                color=ld.color,
                is_active=ld.is_active,
                created_at=ld.created_at,
                updated_at=ld.updated_at,
            )

        pl, _ = ProjectLabel.objects.get_or_create(
            project_id=ld.project_id,
            label_id=label.id,
            defaults={"sort_order": ld.sort_order},
        )
        if pl.sort_order != ld.sort_order:
            pl.sort_order = ld.sort_order
            pl.save(update_fields=["sort_order"])
        ld_to_pl[ld.id] = pl.id

    for ann in SegmentAnnotation.objects.all():
        new_id = ld_to_pl.get(ann.label_id)
        if new_id is not None:
            ann.project_label_id = new_id
            ann.save(update_fields=["project_label_id"])


def backwards_migrate_labels(apps, schema_editor):
    raise RuntimeError("0004_annotahub_labels is irreversible")


class Migration(migrations.Migration):
    dependencies = [
        ("workspace", "0003_user_auth_a1"),
    ]

    operations = [
        migrations.CreateModel(
            name="Label",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "description",
                    models.CharField(blank=True, max_length=2000, null=True),
                ),
                ("color", models.CharField(blank=True, max_length=32, null=True)),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="When false, label cannot be added to new projects.",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="labels",
                        to="workspace.appuser",
                    ),
                ),
            ],
            options={
                "db_table": "labels",
                "ordering": ["name"],
            },
        ),
        migrations.AddConstraint(
            model_name="label",
            constraint=models.UniqueConstraint(
                Lower("name"),
                models.F("owner"),
                name="uq_label_owner_name_lower",
            ),
        ),
        migrations.CreateModel(
            name="ProjectLabel",
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
                (
                    "override_name",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    "override_description",
                    models.CharField(blank=True, max_length=2000, null=True),
                ),
                (
                    "override_color",
                    models.CharField(blank=True, max_length=32, null=True),
                ),
                ("sort_order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "label",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_labels",
                        to="workspace.label",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_labels",
                        to="workspace.project",
                    ),
                ),
            ],
            options={
                "db_table": "project_labels",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="projectlabel",
            constraint=models.UniqueConstraint(
                fields=("project", "label"),
                name="uq_project_label",
            ),
        ),
        migrations.AddField(
            model_name="segmentannotation",
            name="project_label",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="workspace.projectlabel",
            ),
        ),
        migrations.RunPython(forwards_migrate_labels, backwards_migrate_labels),
        migrations.RemoveField(
            model_name="segmentannotation",
            name="label",
        ),
        migrations.RenameField(
            model_name="segmentannotation",
            old_name="project_label",
            new_name="label",
        ),
        migrations.AlterField(
            model_name="segmentannotation",
            name="label",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="annotations",
                to="workspace.projectlabel",
            ),
        ),
        migrations.DeleteModel(
            name="LabelDefinition",
        ),
    ]
