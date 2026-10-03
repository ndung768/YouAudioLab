"""Work queue — AnnotationAssignment lifecycle (distinct from SegmentAnnotation)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from apps.core.errors import ForbiddenError, NotFoundError, ValidationError
from apps.workspace.models import (
    AnnotationAssignment,
    AssignmentBatch,
    AudioSegment,
    ProjectMembership,
    SegmentAnnotation,
    VideoSource,
)
from apps.workspace.services.membership import MembershipService


class AssignmentService:
    def __init__(self) -> None:
        self.memberships = MembershipService()

    def get(self, assignment_id: uuid.UUID) -> AnnotationAssignment:
        try:
            return AnnotationAssignment.objects.select_related(
                "segment",
                "assignee",
                "assigned_by",
                "batch",
            ).get(pk=assignment_id)
        except AnnotationAssignment.DoesNotExist as exc:
            raise NotFoundError(
                "Assignment not found",
                details={"assignment_id": str(assignment_id)},
            ) from exc

    def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        status: str | None = None,
        assignee_id: uuid.UUID | None = None,
        source_id: uuid.UUID | None = None,
    ) -> list[AnnotationAssignment]:
        membership = self.memberships.require_member(project_id, actor_user_id)
        qs = AnnotationAssignment.objects.filter(project_id=project_id).select_related(
            "segment__source",
            "assignee",
            "assigned_by",
            "batch",
        )
        if membership.role != ProjectMembership.Role.OWNER:
            qs = qs.filter(assignee_id=actor_user_id)
        if status:
            qs = qs.filter(status=status)
        if assignee_id is not None:
            if membership.role != ProjectMembership.Role.OWNER:
                raise ForbiddenError(
                    "Only OWNER may filter by assignee",
                    details={"project_id": str(project_id)},
                )
            qs = qs.filter(assignee_id=assignee_id)
        if source_id is not None:
            qs = qs.filter(segment__source_id=source_id)
        return list(qs.order_by("-priority", "-created_at"))

    def list_mine(
        self,
        project_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        status: str | None = None,
    ) -> list[AnnotationAssignment]:
        self.memberships.require_member(project_id, actor_user_id)
        qs = AnnotationAssignment.objects.filter(
            project_id=project_id,
            assignee_id=actor_user_id,
        ).select_related("segment__source", "assigned_by", "batch")
        if status:
            qs = qs.filter(status=status)
        return list(qs.order_by("-priority", "created_at"))

    def _pick_segments(
        self,
        *,
        project_id: uuid.UUID,
        source_id: uuid.UUID | None,
        segment_ids: list[uuid.UUID] | None,
        limit: int | None,
    ) -> list[AudioSegment]:
        qs = AudioSegment.objects.filter(
            source__project_id=project_id,
            deleted_at__isnull=True,
        ).select_related("source")
        if segment_ids:
            qs = qs.filter(id__in=segment_ids)
        elif source_id is not None:
            if not VideoSource.objects.filter(pk=source_id, project_id=project_id).exists():
                raise NotFoundError(
                    "Source not found",
                    details={"source_id": str(source_id)},
                )
            qs = qs.filter(source_id=source_id)
        qs = qs.order_by("source__created_at", "segment_index")
        if limit is not None and limit > 0:
            qs = qs[:limit]
        return list(qs)

    def _active_members(self, project_id: uuid.UUID, assignee_ids: list[uuid.UUID]) -> None:
        assignee_ids = [uuid.UUID(str(uid)) for uid in assignee_ids]
        active = set(
            ProjectMembership.objects.filter(
                project_id=project_id,
                revoked_at__isnull=True,
                user_id__in=assignee_ids,
            ).values_list("user_id", flat=True),
        )
        missing = [str(uid) for uid in assignee_ids if uid not in active]
        if missing:
            raise ValidationError(
                "Assignee must be an active project member",
                details={"fields": [{"field": "assignee_ids", "code": "INVALID_MEMBER"}]},
            )

    @transaction.atomic
    def create_batch(
        self,
        *,
        project_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        assignee_ids: list[uuid.UUID],
        source_id: uuid.UUID | None = None,
        segment_ids: list[uuid.UUID] | None = None,
        limit: int | None = None,
        distribute: str = "split",
        priority: int = 0,
        name: str | None = None,
        notes: str | None = None,
        assignment_group_id: uuid.UUID | None = None,
    ) -> tuple[AssignmentBatch, list[AnnotationAssignment]]:
        self.memberships.require_owner(project_id, actor_user_id)
        self.memberships.require_active_project(project_id)

        if not assignee_ids:
            raise ValidationError(
                "At least one assignee is required",
                details={"fields": [{"field": "assignee_ids", "code": "REQUIRED"}]},
            )
        self._active_members(project_id, assignee_ids)

        segments = self._pick_segments(
            project_id=project_id,
            source_id=source_id,
            segment_ids=segment_ids,
            limit=limit,
        )
        if not segments:
            raise ValidationError(
                "No segments matched the selection",
                details={"fields": [{"field": "segment_ids", "code": "EMPTY"}]},
            )

        group_id = assignment_group_id or uuid.uuid4()
        batch = AssignmentBatch.objects.create(
            project_id=project_id,
            created_by_id=actor_user_id,
            name=name,
            source_id=source_id,
            assignment_group_id=group_id,
            notes=notes,
        )

        created: list[AnnotationAssignment] = []
        if distribute == "all":
            pairs = [(seg, aid) for seg in segments for aid in assignee_ids]
        else:
            pairs = [
                (segments[i], assignee_ids[i % len(assignee_ids)])
                for i in range(len(segments))
            ]

        for segment, assignee_id in pairs:
            if self._has_active(segment.id, assignee_id, group_id):
                continue
            created.append(
                AnnotationAssignment.objects.create(
                    project_id=project_id,
                    segment_id=segment.id,
                    assignee_id=assignee_id,
                    assigned_by_id=actor_user_id,
                    batch_id=batch.id,
                    assignment_group_id=group_id,
                    status=AnnotationAssignment.Status.ASSIGNED,
                    priority=priority,
                ),
            )
        return batch, created

    def _has_active(
        self,
        segment_id: uuid.UUID,
        assignee_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> bool:
        return AnnotationAssignment.objects.filter(
            segment_id=segment_id,
            assignee_id=assignee_id,
            assignment_group_id=group_id,
            status__in=AnnotationAssignment.ACTIVE_STATUSES,
        ).exists()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _lock_in_project(
        self,
        assignment_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> AnnotationAssignment:
        try:
            return (
                AnnotationAssignment.objects.select_for_update(of=("self",))
                .select_related("segment", "assignee", "assigned_by", "batch")
                .get(pk=uuid.UUID(str(assignment_id)), project_id=project_id)
            )
        except AnnotationAssignment.DoesNotExist as exc:
            raise NotFoundError(
                "Assignment not found",
                details={
                    "assignment_id": str(assignment_id),
                    "project_id": str(project_id),
                },
            ) from exc

    def _active_successor(
        self,
        assignment: AnnotationAssignment,
        assignee_id: uuid.UUID,
    ) -> AnnotationAssignment | None:
        return (
            AnnotationAssignment.objects.filter(
                project_id=assignment.project_id,
                segment_id=assignment.segment_id,
                assignee_id=assignee_id,
                assignment_group_id=assignment.assignment_group_id,
                status__in=AnnotationAssignment.ACTIVE_STATUSES,
            )
            .exclude(pk=assignment.pk)
            .order_by("-created_at")
            .first()
        )

    @transaction.atomic
    def start(
        self,
        assignment_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> AnnotationAssignment:
        assignment = self._lock_in_project(assignment_id, project_id)
        self.memberships.require_member(project_id, actor_user_id)
        if assignment.assignee_id != actor_user_id:
            self.memberships.require_owner(project_id, actor_user_id)
        if assignment.status != AnnotationAssignment.Status.ASSIGNED:
            return assignment
        assignment.status = AnnotationAssignment.Status.IN_PROGRESS
        assignment.started_at = self._now()
        assignment.save(update_fields=["status", "started_at"])
        return assignment

    @transaction.atomic
    def complete(
        self,
        assignment_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> AnnotationAssignment:
        assignment = self._lock_in_project(assignment_id, project_id)
        self.memberships.require_member(project_id, actor_user_id)
        if assignment.assignee_id != actor_user_id:
            self.memberships.require_owner(project_id, actor_user_id)
        if assignment.status == AnnotationAssignment.Status.COMPLETED:
            return assignment
        if assignment.status == AnnotationAssignment.Status.RELEASED:
            raise ValidationError(
                "Released assignment cannot be completed",
                details={"assignment_id": str(assignment_id)},
            )
        assignment.status = AnnotationAssignment.Status.COMPLETED
        now = self._now()
        if assignment.started_at is None:
            assignment.started_at = now
        assignment.completed_at = now
        assignment.save(update_fields=["status", "started_at", "completed_at"])
        return assignment

    @transaction.atomic
    def release(
        self,
        assignment_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> AnnotationAssignment:
        assignment = self._lock_in_project(assignment_id, project_id)
        self.memberships.require_owner(project_id, actor_user_id)
        if assignment.status == AnnotationAssignment.Status.RELEASED:
            return assignment
        assignment.status = AnnotationAssignment.Status.RELEASED
        assignment.released_at = self._now()
        assignment.save(update_fields=["status", "released_at"])
        return assignment

    @transaction.atomic
    def reassign(
        self,
        assignment_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        new_assignee_id: uuid.UUID,
    ) -> AnnotationAssignment:
        new_assignee_id = uuid.UUID(str(new_assignee_id))
        old = self._lock_in_project(assignment_id, project_id)
        self.memberships.require_owner(project_id, actor_user_id)
        self.memberships.require_active_project(project_id)

        if old.status == AnnotationAssignment.Status.RELEASED:
            successor = self._active_successor(old, new_assignee_id)
            if successor is not None:
                return successor
            raise ValidationError(
                "Released assignment cannot be reassigned",
                details={"assignment_id": str(assignment_id)},
            )
        if old.status == AnnotationAssignment.Status.COMPLETED:
            raise ValidationError(
                "Completed assignment cannot be reassigned",
                details={"assignment_id": str(assignment_id)},
            )
        if old.assignee_id == new_assignee_id:
            return old

        self._active_members(project_id, [new_assignee_id])
        if self._has_active(old.segment_id, new_assignee_id, old.assignment_group_id):
            raise ValidationError(
                "Assignee already has an active assignment for this segment in this group",
                details={"assignee_id": str(new_assignee_id)},
            )

        old.status = AnnotationAssignment.Status.RELEASED
        old.released_at = self._now()
        old.save(update_fields=["status", "released_at"])
        try:
            return AnnotationAssignment.objects.create(
                project_id=project_id,
                segment_id=old.segment_id,
                assignee_id=new_assignee_id,
                assigned_by_id=actor_user_id,
                batch_id=old.batch_id,
                assignment_group_id=old.assignment_group_id,
                status=AnnotationAssignment.Status.ASSIGNED,
                priority=old.priority,
            )
        except IntegrityError:
            successor = self._active_successor(old, new_assignee_id)
            if successor is None:
                raise
            return successor

    def mark_in_progress_for_workspace(
        self,
        *,
        project_id: uuid.UUID,
        segment_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> None:
        qs = AnnotationAssignment.objects.filter(
            project_id=project_id,
            segment_id=segment_id,
            assignee_id=actor_user_id,
            status=AnnotationAssignment.Status.ASSIGNED,
        )
        now = self._now()
        for assignment in qs:
            assignment.status = AnnotationAssignment.Status.IN_PROGRESS
            assignment.started_at = now
            assignment.save(update_fields=["status", "started_at"])

    def try_auto_complete_for_annotation(
        self,
        *,
        segment_id: uuid.UUID,
        annotator_id: uuid.UUID,
    ) -> None:
        qs = AnnotationAssignment.objects.filter(
            segment_id=segment_id,
            assignee_id=annotator_id,
            status__in=AnnotationAssignment.ACTIVE_STATUSES,
        )
        now = self._now()
        for assignment in qs:
            assignment.status = AnnotationAssignment.Status.COMPLETED
            if assignment.started_at is None:
                assignment.started_at = now
            assignment.completed_at = now
            assignment.save(update_fields=["status", "started_at", "completed_at"])

    def release_for_user_in_project(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        now = self._now()
        updated = AnnotationAssignment.objects.filter(
            project_id=project_id,
            assignee_id=user_id,
            status__in=AnnotationAssignment.ACTIVE_STATUSES,
        ).update(status=AnnotationAssignment.Status.RELEASED, released_at=now)
        return updated

    def release_for_segment(self, segment_id: uuid.UUID) -> int:
        now = self._now()
        return AnnotationAssignment.objects.filter(
            segment_id=segment_id,
            status__in=AnnotationAssignment.ACTIVE_STATUSES,
        ).update(status=AnnotationAssignment.Status.RELEASED, released_at=now)

    def next_assigned_segment(
        self,
        project_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> AudioSegment | None:
        row = (
            AnnotationAssignment.objects.filter(
                project_id=project_id,
                assignee_id=user_id,
                status__in=[
                    AnnotationAssignment.Status.ASSIGNED,
                    AnnotationAssignment.Status.IN_PROGRESS,
                ],
                segment__deleted_at__isnull=True,
            )
            .select_related("segment__source")
            .order_by("-priority", "created_at")
            .first()
        )
        return row.segment if row else None

    def assignment_status_counts(self, project_id: uuid.UUID) -> dict[str, int]:
        rows = (
            AnnotationAssignment.objects.filter(project_id=project_id)
            .values("status")
            .annotate(n=Count("id"))
        )
        return {row["status"]: row["n"] for row in rows}

    def assignee_workload(self, project_id: uuid.UUID) -> list[dict]:
        active = AnnotationAssignment.ACTIVE_STATUSES
        rows = (
            AnnotationAssignment.objects.filter(project_id=project_id)
            .values("assignee_id", "assignee__display_name")
            .annotate(
                assigned=Count("id", filter=Q(status=AnnotationAssignment.Status.ASSIGNED)),
                in_progress=Count("id", filter=Q(status=AnnotationAssignment.Status.IN_PROGRESS)),
                completed=Count("id", filter=Q(status=AnnotationAssignment.Status.COMPLETED)),
                active=Count("id", filter=Q(status__in=active)),
            )
            .order_by("-active", "assignee__display_name")
        )
        return [
            {
                "assignee_id": row["assignee_id"],
                "display_name": row["assignee__display_name"],
                "assigned": row["assigned"],
                "in_progress": row["in_progress"],
                "completed": row["completed"],
                "active": row["active"],
            }
            for row in rows
        ]
