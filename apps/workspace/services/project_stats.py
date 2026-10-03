"""Project-level progress metrics for overview and quality dashboards."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from django.db.models import Count, Q

from apps.processing.models import ProcessingJob
from apps.workspace.models import (
    AnnotationAssignment,
    AudioSegment,
    ProjectLabel,
    ProjectMembership,
    SegmentAnnotation,
    VideoSource,
)
from apps.workspace.services.assignment import AssignmentService


@dataclass(frozen=True)
class AnnotatorProgressRow:
    annotator_id: uuid.UUID
    display_name: str
    episode_count: int
    segment_count: int


@dataclass(frozen=True)
class ProjectProgressStats:
    source_count: int
    segment_count: int
    segments_annotated: int
    annotation_count: int
    segments_with_transcript: int
    segments_with_artifact: int
    project_label_count: int
    member_count: int
    jobs_active: int
    jobs_failed: int
    extract_jobs_active: int
    asr_jobs_active: int
    segment_status_counts: dict[str, int] = field(default_factory=dict)
    job_status_counts: dict[str, int] = field(default_factory=dict)
    assignment_status_counts: dict[str, int] = field(default_factory=dict)
    assignments_active: int = 0
    segments_ready: int = 0
    segments_not_ready: int = 0
    need_review: int = 0
    need_transcript: int = 0
    need_annotation: int = 0
    need_artifact: int = 0
    failed_processing: int = 0

    @property
    def annotated_pct(self) -> int:
        if self.segment_count == 0:
            return 0
        return round(100 * self.segments_annotated / self.segment_count)

    @property
    def transcript_pct(self) -> int:
        if self.segment_count == 0:
            return 0
        return round(100 * self.segments_with_transcript / self.segment_count)

    @property
    def artifact_pct(self) -> int:
        if self.segment_count == 0:
            return 0
        return round(100 * self.segments_with_artifact / self.segment_count)

    @property
    def ready_pct(self) -> int:
        if self.segment_count == 0:
            return 0
        return round(100 * self.segments_ready / self.segment_count)


class ProjectStatsService:
    def _segments_qs(self, project_id: uuid.UUID):
        return AudioSegment.objects.filter(
            source__project_id=project_id,
            deleted_at__isnull=True,
        )

    def get_stats(self, project_id: uuid.UUID) -> ProjectProgressStats:
        segments_qs = self._segments_qs(project_id)
        segment_count = segments_qs.count()

        segments_annotated = (
            segments_qs.filter(annotations__removed_at__isnull=True).distinct().count()
            if segment_count
            else 0
        )
        annotation_count = SegmentAnnotation.objects.filter(
            segment__source__project_id=project_id,
            removed_at__isnull=True,
        ).count()

        segments_with_transcript = segments_qs.exclude(
            Q(transcript__isnull=True) | Q(transcript=""),
        ).count()
        segments_with_artifact = segments_qs.filter(current_artifact_id__isnull=False).count()

        active_jobs = ProcessingJob.objects.filter(
            project_id=project_id,
            status__in=[ProcessingJob.Status.QUEUED, ProcessingJob.Status.RUNNING],
        )
        jobs_active = active_jobs.count()
        extract_jobs_active = active_jobs.filter(
            job_type=ProcessingJob.JobType.EXTRACT_SEGMENT_AUDIO,
        ).count()
        asr_jobs_active = active_jobs.filter(
            job_type=ProcessingJob.JobType.TRANSCRIBE_SEGMENT_AUDIO,
        ).count()
        jobs_failed = ProcessingJob.objects.filter(
            project_id=project_id,
            status=ProcessingJob.Status.FAILED,
        ).count()

        segment_status_counts = {
            row["processing_status"]: row["n"]
            for row in segments_qs.values("processing_status").annotate(n=Count("id"))
        }
        job_status_counts = {
            row["status"]: row["n"]
            for row in ProcessingJob.objects.filter(project_id=project_id)
            .values("status")
            .annotate(n=Count("id"))
        }

        assignment_status_counts = AssignmentService().assignment_status_counts(project_id)
        assignments_active = (
            assignment_status_counts.get(AnnotationAssignment.Status.ASSIGNED, 0)
            + assignment_status_counts.get(AnnotationAssignment.Status.IN_PROGRESS, 0)
        )

        from apps.workspace.services.readiness import ReadinessService

        readiness = ReadinessService().counts_for_project(project_id)

        return ProjectProgressStats(
            source_count=VideoSource.objects.filter(project_id=project_id).count(),
            segment_count=segment_count,
            segments_annotated=segments_annotated,
            annotation_count=annotation_count,
            segments_with_transcript=segments_with_transcript,
            segments_with_artifact=segments_with_artifact,
            project_label_count=ProjectLabel.objects.filter(project_id=project_id).count(),
            member_count=ProjectMembership.objects.filter(
                project_id=project_id,
                revoked_at__isnull=True,
            ).count(),
            jobs_active=jobs_active,
            jobs_failed=jobs_failed,
            extract_jobs_active=extract_jobs_active,
            asr_jobs_active=asr_jobs_active,
            segment_status_counts=segment_status_counts,
            job_status_counts=job_status_counts,
            assignment_status_counts=assignment_status_counts,
            assignments_active=assignments_active,
            segments_ready=readiness.ready,
            segments_not_ready=readiness.not_ready,
            need_review=readiness.need_review,
            need_transcript=readiness.need_transcript,
            need_annotation=readiness.need_annotation,
            need_artifact=readiness.need_artifact,
            failed_processing=readiness.failed_processing,
        )

    def next_labeling_segment(
        self,
        project_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
    ) -> AudioSegment | None:
        segments_qs = self._segments_qs(project_id).select_related("source")
        if not segments_qs.exists():
            return None

        if user_id is not None:
            assigned = AssignmentService().next_assigned_segment(project_id, user_id=user_id)
            if assigned is not None:
                return assigned

        if user_id is not None:
            mine_annotated = SegmentAnnotation.objects.filter(
                annotator_id=user_id,
                removed_at__isnull=True,
                segment__source__project_id=project_id,
            ).values_list("segment_id", flat=True)
            pending = segments_qs.exclude(id__in=mine_annotated).order_by(
                "source__created_at",
                "segment_index",
            )
            found = pending.first()
            if found is not None:
                return found

        team_annotated = SegmentAnnotation.objects.filter(
            segment__source__project_id=project_id,
            removed_at__isnull=True,
        ).values_list("segment_id", flat=True)
        pending = segments_qs.exclude(id__in=team_annotated).order_by(
            "source__created_at",
            "segment_index",
        )
        found = pending.first()
        if found is not None:
            return found

        return segments_qs.order_by("source__created_at", "segment_index").first()

    def annotator_progress(self, project_id: uuid.UUID) -> list[AnnotatorProgressRow]:
        rows = (
            SegmentAnnotation.objects.filter(
                segment__source__project_id=project_id,
                removed_at__isnull=True,
            )
            .values("annotator_id", "annotator__display_name")
            .annotate(
                episode_count=Count("id"),
                segment_count=Count("segment_id", distinct=True),
            )
            .order_by("-episode_count", "annotator__display_name")
        )
        return [
            AnnotatorProgressRow(
                annotator_id=row["annotator_id"],
                display_name=row["annotator__display_name"],
                episode_count=row["episode_count"],
                segment_count=row["segment_count"],
            )
            for row in rows
        ]

    def recent_sources(self, project_id: uuid.UUID, *, limit: int = 8) -> list[VideoSource]:
        return list(
            VideoSource.objects.filter(project_id=project_id)
            .order_by("-created_at")[:limit],
        )
