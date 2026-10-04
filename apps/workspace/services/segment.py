"""Audio segment domain service — revision-aware mutate / soft-delete."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from django.db import transaction
from django.db.models import Count, Max

from apps.core.errors import (
    NotFoundError,
    SegmentDeletedError,
    SegmentRevisionConflictError,
    ValidationError,
)
from apps.core.segment_rules import bounds_changed, validate_segment_bounds
from apps.workspace.models import (
    AnnotationAssignment,
    AudioSegment,
    SegmentAnnotation,
    VideoSource,
)
from apps.workspace.services.membership import MembershipService


@dataclass
class SegmentIndexRow:
    segment: AudioSegment
    active_annotation_count: int
    annotator_count: int
    label_names: list[str]
    chips: list[dict]
    has_transcript: bool
    has_asr: bool
    has_artifact: bool
    my_assignment_status: str | None
    readiness_status: str = "NOT_READY"
    readiness_failed_gates: tuple[str, ...] = ()
    audio_reviewed: bool = False

    @property
    def is_ready(self) -> bool:
        return self.readiness_status == "READY"


@dataclass
class SegmentSourceGroup:
    source: VideoSource
    rows: list[SegmentIndexRow] = field(default_factory=list)

    @property
    def segment_count(self) -> int:
        return len(self.rows)

    @property
    def annotated_count(self) -> int:
        return sum(1 for row in self.rows if row.active_annotation_count > 0)

    @property
    def mine_labeled_count(self) -> int:
        return sum(1 for row in self.rows if any(chip.get("annotation_id") for chip in row.chips))


def group_index_rows_by_source(rows: list[SegmentIndexRow]) -> list[SegmentSourceGroup]:
    groups: list[SegmentSourceGroup] = []
    by_id: dict[uuid.UUID, SegmentSourceGroup] = {}
    for row in rows:
        source = row.segment.source
        group = by_id.get(source.id)
        if group is None:
            group = SegmentSourceGroup(source=source)
            by_id[source.id] = group
            groups.append(group)
        group.rows.append(row)
    return groups


class SegmentService:
    def __init__(self) -> None:
        self.memberships = MembershipService()

    def get(self, segment_id: uuid.UUID) -> AudioSegment:
        try:
            return AudioSegment.objects.select_related(
                "source",
                "current_artifact",
                "current_artifact__job",
                "audio_reviewed_by",
            ).get(pk=segment_id)
        except AudioSegment.DoesNotExist as exc:
            raise NotFoundError(
                "Segment not found",
                details={"segment_id": str(segment_id)},
            ) from exc

    def _lock_segment(self, segment_id: uuid.UUID) -> AudioSegment:
        try:
            return AudioSegment.objects.select_for_update().get(pk=segment_id)
        except AudioSegment.DoesNotExist as exc:
            raise NotFoundError(
                "Segment not found",
                details={"segment_id": str(segment_id)},
            ) from exc

    def create(
        self,
        *,
        source_id: uuid.UUID,
        start_seconds: float,
        end_seconds: float,
        actor_user_id: uuid.UUID,
        transcript: str | None = None,
    ) -> AudioSegment:
        try:
            source = VideoSource.objects.get(pk=source_id)
        except VideoSource.DoesNotExist as exc:
            raise NotFoundError(
                "Source not found",
                details={"source_id": str(source_id)},
            ) from exc
        self.memberships.require_owner(source.project_id, actor_user_id)
        self.memberships.require_active_project(source.project_id)

        duration = validate_segment_bounds(
            start_seconds,
            end_seconds,
            source_duration_seconds=source.duration_seconds,
        )
        next_index = (
            AudioSegment.objects.filter(source_id=source_id).aggregate(
                m=Max("segment_index")
            )["m"]
            or 0
        )
        return AudioSegment.objects.create(
            source=source,
            segment_index=int(next_index) + 1,
            start_seconds=float(start_seconds),
            end_seconds=float(end_seconds),
            duration_seconds=duration,
            transcript=transcript,
            definition_revision=1,
            processing_status=AudioSegment.ProcessingStatus.PENDING,
        )

    def list_for_source(
        self,
        source_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> list[AudioSegment]:
        qs = (
            AudioSegment.objects.filter(source_id=source_id)
            .select_related(
                "source",
                "current_artifact",
                "current_artifact__job",
                "audio_reviewed_by",
            )
            .order_by("segment_index")
        )
        if not include_deleted:
            qs = qs.filter(deleted_at__isnull=True)
        return list(qs)

    def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> list[AudioSegment]:
        qs = AudioSegment.objects.filter(source__project_id=project_id).select_related(
            "source"
        ).order_by("source__created_at", "segment_index")
        if not include_deleted:
            qs = qs.filter(deleted_at__isnull=True)
        return list(qs)

    def list_index_rows(
        self,
        project_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        source_id: uuid.UUID | None = None,
        annotated: str | None = None,
        mine: bool = False,
        processing: str | None = None,
        ready: str | None = None,
        project_labels: list | None = None,
        blind: bool = False,
    ) -> list[SegmentIndexRow]:
        """Build segment index rows.

        When ``blind`` is True (ANNOTATOR protocol), team label names and
        annotator counts are hidden; only the actor's own active labels show.
        """
        qs = (
            AudioSegment.objects.filter(source__project_id=project_id, deleted_at__isnull=True)
            .select_related(
                "source",
                "current_artifact",
                "current_artifact__job",
                "audio_reviewed_by",
            )
            .order_by("source__created_at", "segment_index")
        )
        if source_id is not None:
            qs = qs.filter(source_id=source_id)
        if processing:
            qs = qs.filter(processing_status=processing)
        annotated_qs = SegmentAnnotation.objects.filter(
            segment__source__project_id=project_id,
            removed_at__isnull=True,
        )
        if blind:
            annotated_qs = annotated_qs.filter(annotator_id=actor_user_id)
        if annotated == "yes":
            qs = qs.filter(id__in=annotated_qs.values_list("segment_id", flat=True))
        elif annotated == "no":
            qs = qs.exclude(id__in=annotated_qs.values_list("segment_id", flat=True))
        if mine:
            qs = qs.filter(
                assignments__assignee_id=actor_user_id,
                assignments__status__in=AnnotationAssignment.ACTIVE_STATUSES,
            ).distinct()

        segments = list(qs)
        if not segments:
            return []

        from apps.workspace.services.readiness import ReadinessService

        readiness_map = ReadinessService().evaluate_many(segments, project_id=project_id)
        if ready == "yes":
            segments = [s for s in segments if readiness_map[s.id].is_ready]
        elif ready == "no":
            segments = [s for s in segments if not readiness_map[s.id].is_ready]
        if not segments:
            return []

        segment_ids = [segment.id for segment in segments]
        ann_filter = SegmentAnnotation.objects.filter(
            segment_id__in=segment_ids,
            removed_at__isnull=True,
        )
        if blind:
            ann_filter = ann_filter.filter(annotator_id=actor_user_id)
        ann_stats = {
            row["segment_id"]: row
            for row in ann_filter.values("segment_id").annotate(
                active_annotation_count=Count("id"),
                annotator_count=Count("annotator_id", distinct=True),
            )
        }
        labels_by_segment: dict[uuid.UUID, list[str]] = {}
        mine_by_segment: dict[uuid.UUID, dict] = {}
        for row in (
            SegmentAnnotation.objects.filter(
                segment_id__in=segment_ids,
                removed_at__isnull=True,
            )
            .select_related("label__label", "annotator")
            .order_by("created_at")
        ):
            if blind and row.annotator_id != actor_user_id:
                continue
            name = row.label.display_name
            names = labels_by_segment.setdefault(row.segment_id, [])
            if name not in names:
                names.append(name)
            if row.annotator_id == actor_user_id:
                mine_by_segment.setdefault(row.segment_id, {})[row.label_id] = row
        my_assignments: dict = {}
        for row in AnnotationAssignment.objects.filter(
            segment_id__in=segment_ids,
            assignee_id=actor_user_id,
            status__in=[
                AnnotationAssignment.Status.ASSIGNED,
                AnnotationAssignment.Status.IN_PROGRESS,
                AnnotationAssignment.Status.COMPLETED,
            ],
        ).order_by("created_at"):
            current = my_assignments.get(row.segment_id)
            if current in AnnotationAssignment.ACTIVE_STATUSES:
                continue
            my_assignments[row.segment_id] = row.status

        rows: list[SegmentIndexRow] = []
        labels = project_labels or []
        for segment in segments:
            stats = ann_stats.get(segment.id, {})
            transcript = (segment.transcript or "").strip()
            label_names = labels_by_segment.get(segment.id, [])
            mine_map = mine_by_segment.get(segment.id, {})
            chips = []
            for pl in labels:
                mine_ann = mine_map.get(pl.id)
                chips.append(
                    {
                        "label_id": pl.id,
                        "name": pl.display_name,
                        "annotation_id": mine_ann.id if mine_ann is not None else None,
                    }
                )
            readiness = readiness_map[segment.id]
            rows.append(
                SegmentIndexRow(
                    segment=segment,
                    active_annotation_count=stats.get("active_annotation_count", 0),
                    annotator_count=stats.get("annotator_count", 0),
                    label_names=label_names,
                    chips=chips,
                    has_transcript=bool(transcript),
                    has_asr=segment.current_asr_run_id is not None,
                    has_artifact=segment.current_artifact_id is not None,
                    my_assignment_status=my_assignments.get(segment.id),
                    readiness_status=readiness.status,
                    readiness_failed_gates=readiness.failed_gates,
                    audio_reviewed=segment.audio_reviewed_at is not None,
                )
            )
        return rows

    def neighbors(
        self,
        project_id: uuid.UUID,
        segment_id: uuid.UUID,
    ) -> tuple[AudioSegment | None, AudioSegment | None]:
        ordered = list(
            AudioSegment.objects.filter(
                source__project_id=project_id,
                deleted_at__isnull=True,
            )
            .select_related("source")
            .order_by("source__created_at", "segment_index", "id")
        )
        prev_seg = next_seg = None
        for index, item in enumerate(ordered):
            if item.id == segment_id:
                if index > 0:
                    prev_seg = ordered[index - 1]
                if index + 1 < len(ordered):
                    next_seg = ordered[index + 1]
                break
        return prev_seg, next_seg

    def update(
        self,
        segment_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        expected_definition_revision: int,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
        transcript: str | None | object = ...,
    ) -> AudioSegment:
        if expected_definition_revision is None:
            raise ValidationError(
                "expected_definition_revision is required",
                details={
                    "fields": [
                        {
                            "field": "expected_definition_revision",
                            "code": "REQUIRED",
                        }
                    ]
                },
            )

        with transaction.atomic():
            segment = self._lock_segment(segment_id)
            if segment.deleted_at is not None:
                raise SegmentDeletedError(
                    "Segment is soft-deleted",
                    details={"segment_id": str(segment_id)},
                )

            source = VideoSource.objects.get(pk=segment.source_id)
            self.memberships.require_owner(source.project_id, actor_user_id)
            self.memberships.require_active_project(source.project_id)

            if segment.definition_revision != expected_definition_revision:
                raise SegmentRevisionConflictError(
                    "Segment definition_revision conflict",
                    details={
                        "segment_id": str(segment_id),
                        "current_definition_revision": segment.definition_revision,
                        "expected_definition_revision": expected_definition_revision,
                    },
                )

            new_start = segment.start_seconds if start_seconds is None else float(start_seconds)
            new_end = segment.end_seconds if end_seconds is None else float(end_seconds)
            changed = bounds_changed(
                old_start=segment.start_seconds,
                old_end=segment.end_seconds,
                new_start=new_start,
                new_end=new_end,
            )

            if changed:
                duration = validate_segment_bounds(
                    new_start,
                    new_end,
                    source_duration_seconds=source.duration_seconds,
                )
                segment.start_seconds = new_start
                segment.end_seconds = new_end
                segment.duration_seconds = duration
                segment.definition_revision += 1
                segment.current_job = None
                segment.current_artifact = None
                segment.current_asr_job = None
                segment.current_asr_run = None
                segment.audio_reviewed_at = None
                segment.audio_reviewed_by = None
                segment.processing_status = AudioSegment.ProcessingStatus.PENDING
                self._request_cancel_active_jobs(segment.id)

            transcript_changed = False
            if transcript is not ...:
                incoming = "" if transcript is None else str(transcript)
                transcript_changed = (segment.transcript or "") != incoming
                segment.transcript = transcript  # type: ignore[assignment]

            segment.save()
            if changed or transcript_changed:
                from apps.workspace.services.transcript_span import TranscriptSpanService

                TranscriptSpanService().mark_stale(segment.id)
            return segment

    def mark_audio_reviewed(
        self,
        segment_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        reviewed: bool = True,
    ) -> AudioSegment:
        with transaction.atomic():
            segment = self._lock_segment(segment_id)
            if segment.deleted_at is not None:
                raise SegmentDeletedError(
                    "Segment is soft-deleted",
                    details={"segment_id": str(segment_id)},
                )
            source = VideoSource.objects.get(pk=segment.source_id)
            self.memberships.require_owner(source.project_id, actor_user_id)
            self.memberships.require_active_project(source.project_id)

            if reviewed:
                if segment.current_artifact_id is None:
                    raise ValidationError(
                        "Cannot mark Audio OK without a current artifact",
                        details={"segment_id": str(segment_id)},
                    )
                segment.audio_reviewed_at = datetime.now(timezone.utc)
                segment.audio_reviewed_by_id = actor_user_id
            else:
                segment.audio_reviewed_at = None
                segment.audio_reviewed_by = None
            segment.save(
                update_fields=[
                    "audio_reviewed_at",
                    "audio_reviewed_by",
                    "updated_at",
                ]
            )
            return segment

    def soft_delete(
        self,
        segment_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> AudioSegment:
        with transaction.atomic():
            segment = self._lock_segment(segment_id)
            source = VideoSource.objects.get(pk=segment.source_id)
            self.memberships.require_owner(source.project_id, actor_user_id)
            self.memberships.require_active_project(source.project_id)

            if segment.deleted_at is None:
                segment.deleted_at = datetime.now(timezone.utc)
                self._request_cancel_active_jobs(segment.id)
                segment.save(update_fields=["deleted_at", "updated_at"])
                from apps.workspace.services.assignment import AssignmentService

                AssignmentService().release_for_segment(segment.id)
            return segment

    def _request_cancel_active_jobs(self, segment_id: uuid.UUID) -> None:
        from apps.processing.models import ProcessingJob

        now = datetime.now(timezone.utc)
        jobs = (
            ProcessingJob.objects.select_for_update()
            .filter(
                segment_id=segment_id,
                status__in=[ProcessingJob.Status.QUEUED, ProcessingJob.Status.RUNNING],
                cancel_requested_at__isnull=True,
            )
            .order_by("id")
        )
        for job in jobs:
            job.cancel_requested_at = now
            job.save(update_fields=["cancel_requested_at"])
