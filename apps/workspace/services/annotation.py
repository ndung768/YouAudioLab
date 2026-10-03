"""Model B SegmentAnnotation service — soft-remove episodes, no revision bump."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from apps.core.errors import (
    ForbiddenError,
    NotFoundError,
    SegmentDeletedError,
    ValidationError,
)
from apps.workspace.models import (
    AudioSegment,
    ProjectLabel,
    ProjectMembership,
    SegmentAnnotation,
)
from apps.workspace.services.membership import MembershipService


class AnnotationService:
    def __init__(self) -> None:
        self.memberships = MembershipService()

    def get(self, annotation_id: uuid.UUID) -> SegmentAnnotation:
        try:
            return SegmentAnnotation.objects.get(pk=annotation_id)
        except SegmentAnnotation.DoesNotExist as exc:
            raise NotFoundError(
                "Annotation not found",
                details={"annotation_id": str(annotation_id)},
            ) from exc

    def _segment_and_project(
        self,
        segment_id: uuid.UUID,
    ) -> tuple[AudioSegment, uuid.UUID]:
        try:
            segment = AudioSegment.objects.select_related("source").get(pk=segment_id)
        except AudioSegment.DoesNotExist as exc:
            raise NotFoundError(
                "Segment not found",
                details={"segment_id": str(segment_id)},
            ) from exc
        source = segment.source
        if source is None:
            raise NotFoundError(
                "Source not found for segment",
                details={"segment_id": str(segment_id)},
            )
        return segment, source.project_id

    def _assert_label_in_project(
        self,
        label_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> ProjectLabel:
        pl = ProjectLabel.objects.select_related("label").filter(pk=label_id).first()
        if pl is None or pl.project_id != project_id:
            raise NotFoundError(
                "Label not found",
                details={"label_id": str(label_id)},
            )
        return pl

    def get_active(
        self,
        *,
        segment_id: uuid.UUID,
        label_id: uuid.UUID,
        annotator_id: uuid.UUID,
    ) -> SegmentAnnotation | None:
        return SegmentAnnotation.objects.filter(
            segment_id=segment_id,
            label_id=label_id,
            annotator_id=annotator_id,
            removed_at__isnull=True,
        ).first()

    def list_for_segment(
        self,
        segment_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        include_removed: bool = False,
        annotator_id: uuid.UUID | None = None,
    ) -> list[SegmentAnnotation]:
        segment, project_id = self._segment_and_project(segment_id)
        self.memberships.require_member(project_id, actor_user_id)

        qs = (
            SegmentAnnotation.objects.filter(segment_id=segment.id)
            .select_related("label__label", "annotator")
            .order_by("created_at")
        )
        if not include_removed:
            qs = qs.filter(removed_at__isnull=True)
        if annotator_id is not None:
            qs = qs.filter(annotator_id=annotator_id)
        return list(qs)

    def assign(
        self,
        *,
        segment_id: uuid.UUID,
        label_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> SegmentAnnotation:
        segment, project_id = self._segment_and_project(segment_id)
        self.memberships.require_member(project_id, actor_user_id)
        self.memberships.require_active_project(project_id)

        if segment.deleted_at is not None:
            raise SegmentDeletedError(
                "Segment is soft-deleted",
                details={"segment_id": str(segment_id)},
            )

        self._assert_label_in_project(label_id, project_id)
        revision_before = segment.definition_revision

        existing = self.get_active(
            segment_id=segment_id,
            label_id=label_id,
            annotator_id=actor_user_id,
        )
        if existing is not None:
            segment.refresh_from_db()
            if segment.definition_revision != revision_before:
                raise ValidationError(
                    "Invariant violated: annotation must not bump definition_revision",
                    details={
                        "segment_id": str(segment_id),
                        "before": revision_before,
                        "after": segment.definition_revision,
                    },
                )
            return existing

        annotation = SegmentAnnotation.objects.create(
            segment_id=segment_id,
            label_id=label_id,
            annotator_id=actor_user_id,
        )
        from apps.workspace.services.assignment import AssignmentService

        AssignmentService().try_auto_complete_for_annotation(
            segment_id=segment_id,
            annotator_id=actor_user_id,
        )
        segment.refresh_from_db()
        if segment.definition_revision != revision_before:
            raise ValidationError(
                "Invariant violated: annotation must not bump definition_revision",
                details={
                    "segment_id": str(segment_id),
                    "before": revision_before,
                    "after": segment.definition_revision,
                },
            )
        return annotation

    def remove(
        self,
        annotation_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> SegmentAnnotation:
        annotation = self.get(annotation_id)
        segment, project_id = self._segment_and_project(annotation.segment_id)
        membership = self.memberships.require_member(project_id, actor_user_id)
        self.memberships.require_active_project(project_id)

        if segment.deleted_at is not None:
            raise SegmentDeletedError(
                "Segment is soft-deleted",
                details={"segment_id": str(segment.id)},
            )

        is_owner = membership.role == ProjectMembership.Role.OWNER
        is_own = annotation.annotator_id == actor_user_id
        if not is_owner and not is_own:
            raise ForbiddenError(
                "ANNOTATOR may only remove own annotations",
                details={
                    "annotation_id": str(annotation_id),
                    "annotator_id": str(annotation.annotator_id),
                },
            )

        if annotation.removed_at is None:
            revision_before = segment.definition_revision
            annotation.removed_at = datetime.now(timezone.utc)
            annotation.removed_by_id = actor_user_id
            annotation.save(update_fields=["removed_at", "removed_by"])
            segment.refresh_from_db()
            if segment.definition_revision != revision_before:
                raise ValidationError(
                    "Invariant violated: annotation remove must not bump definition_revision",
                    details={"segment_id": str(segment.id)},
                )
        return annotation
