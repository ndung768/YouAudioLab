"""OWNER gold / adjudication for a segment (export + training fallback)."""

from __future__ import annotations

import uuid

from django.db import transaction

from apps.core.errors import ForbiddenError, ValidationError
from apps.workspace.models import ProjectLabel, SegmentAnnotation, SegmentGoldLabel
from apps.workspace.services.membership import MembershipService
from apps.workspace.services.segment import SegmentService


class GoldService:
    def __init__(self) -> None:
        self.memberships = MembershipService()
        self.segments = SegmentService()

    def list_for_segment(self, segment_id: uuid.UUID) -> list[SegmentGoldLabel]:
        return list(
            SegmentGoldLabel.objects.filter(segment_id=segment_id)
            .select_related("label__label", "adjudicated_by")
            .order_by("created_at")
        )

    def list_for_project(self, project_id: uuid.UUID) -> list[SegmentGoldLabel]:
        return list(
            SegmentGoldLabel.objects.filter(
                segment__source__project_id=project_id,
                segment__deleted_at__isnull=True,
            )
            .select_related("label__label", "adjudicated_by")
            .order_by("created_at")
        )

    def set_labels(
        self,
        *,
        segment_id: uuid.UUID,
        label_ids: list[uuid.UUID],
        actor_user_id: uuid.UUID,
    ) -> list[SegmentGoldLabel]:
        segment = self.segments.get(segment_id)
        project_id = segment.source.project_id
        membership = self.memberships.require_member(project_id, actor_user_id)
        self.memberships.require_active_project(project_id)
        if membership.role != "OWNER":
            raise ForbiddenError(
                "OWNER role required to adjudicate gold labels",
                details={"project_id": str(project_id), "role": membership.role},
            )

        wanted: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for raw in label_ids:
            lid = uuid.UUID(str(raw))
            if lid in seen:
                continue
            seen.add(lid)
            wanted.append(lid)

        if wanted:
            found = {
                row.id
                for row in ProjectLabel.objects.filter(
                    project_id=project_id, id__in=wanted
                )
            }
            missing = [str(lid) for lid in wanted if lid not in found]
            if missing:
                raise ValidationError(
                    "Gold label is not in this project",
                    details={"fields": [{"field": "label_ids", "code": "INVALID"}]},
                )

        with transaction.atomic():
            SegmentGoldLabel.objects.filter(segment_id=segment.id).exclude(
                label_id__in=wanted
            ).delete()
            existing = {
                row.label_id
                for row in SegmentGoldLabel.objects.filter(segment_id=segment.id)
            }
            for lid in wanted:
                if lid in existing:
                    continue
                SegmentGoldLabel.objects.create(
                    segment_id=segment.id,
                    label_id=lid,
                    adjudicated_by_id=actor_user_id,
                )
        return self.list_for_segment(segment.id)

    def adopt_majority(
        self,
        *,
        segment_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> list[SegmentGoldLabel]:
        segment = self.segments.get(segment_id)
        episodes = list(
            SegmentAnnotation.objects.filter(
                segment_id=segment.id,
                removed_at__isnull=True,
            ).select_related("label")
        )
        by_annotator: dict[uuid.UUID, set[uuid.UUID]] = {}
        order: list[uuid.UUID] = []
        for row in episodes:
            by_annotator.setdefault(row.annotator_id, set()).add(row.label_id)
            if row.label_id not in order:
                order.append(row.label_id)
        annotators = list(by_annotator)
        if not annotators:
            return self.set_labels(
                segment_id=segment.id, label_ids=[], actor_user_id=actor_user_id
            )
        threshold = len(annotators) // 2 + 1
        counts: dict[uuid.UUID, int] = {}
        for labels in by_annotator.values():
            for lid in labels:
                counts[lid] = counts.get(lid, 0) + 1
        kept = [lid for lid in order if counts.get(lid, 0) >= threshold]
        return self.set_labels(
            segment_id=segment.id, label_ids=kept, actor_user_id=actor_user_id
        )
