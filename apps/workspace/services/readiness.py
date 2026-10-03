"""Dataset readiness gates for research export and progress dashboards."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Iterable

from apps.workspace.models import (
    AudioSegment,
    ProjectSettings,
    SegmentAnnotation,
    VideoSource,
)


GATE_SOURCE_VALID = "SOURCE_VALID"
GATE_SEGMENT_VALID = "SEGMENT_VALID"
GATE_AUDIO_VALID = "AUDIO_VALID"
GATE_REVIEW_OK = "AUDIO_REVIEWED"
GATE_TEXT_VALID = "TRANSCRIPT_VALID"
GATE_ANNOTATION_VALID = "ANNOTATION_VALID"
GATE_NOT_DELETED = "NOT_DELETED"

STATUS_READY = "READY"
STATUS_NOT_READY = "NOT_READY"


@dataclass(frozen=True)
class SegmentReadiness:
    segment_id: uuid.UUID
    status: str
    failed_gates: tuple[str, ...] = ()
    passed_gates: tuple[str, ...] = ()

    @property
    def is_ready(self) -> bool:
        return self.status == STATUS_READY


@dataclass(frozen=True)
class ReadinessCounts:
    ready: int = 0
    not_ready: int = 0
    need_review: int = 0
    need_transcript: int = 0
    need_annotation: int = 0
    need_artifact: int = 0
    failed_processing: int = 0


@dataclass
class _Policy:
    require_audio_review: bool = True
    require_transcript: bool = True
    require_annotation: bool = True


class ReadinessService:
    def policy_for_project(self, project_id: uuid.UUID) -> _Policy:
        try:
            settings = ProjectSettings.objects.get(pk=project_id)
        except ProjectSettings.DoesNotExist:
            return _Policy()
        return _Policy(
            require_audio_review=bool(settings.require_audio_review),
            require_transcript=bool(settings.require_transcript),
            require_annotation=bool(settings.require_annotation),
        )

    def evaluate(
        self,
        segment: AudioSegment,
        *,
        policy: _Policy | None = None,
        has_active_annotation: bool | None = None,
    ) -> SegmentReadiness:
        if policy is None:
            policy = self.policy_for_project(segment.source.project_id)

        passed: list[str] = []
        failed: list[str] = []

        def gate(name: str, ok: bool) -> None:
            (passed if ok else failed).append(name)

        deleted = segment.deleted_at is not None
        gate(GATE_NOT_DELETED, not deleted)

        source = segment.source
        source_ok = (
            source.source_status == VideoSource.Status.READY
            and source.duration_seconds is not None
            and source.duration_seconds > 0
        )
        gate(GATE_SOURCE_VALID, source_ok)

        bounds_ok = (
            segment.start_seconds >= 0
            and segment.end_seconds > segment.start_seconds
            and (
                source.duration_seconds is None
                or segment.end_seconds <= float(source.duration_seconds) + 1e-6
            )
        )
        gate(GATE_SEGMENT_VALID, bounds_ok)

        artifact = segment.current_artifact
        job = artifact.job if artifact is not None else None
        audio_ok = (
            artifact is not None
            and artifact.verified
            and job is not None
            and job.expected_revision == segment.definition_revision
            and segment.processing_status == AudioSegment.ProcessingStatus.COMPLETED
        )
        gate(GATE_AUDIO_VALID, audio_ok)

        if policy.require_audio_review:
            gate(GATE_REVIEW_OK, segment.audio_reviewed_at is not None)
        else:
            passed.append(GATE_REVIEW_OK)

        if policy.require_transcript:
            text = (segment.transcript or "").strip()
            gate(GATE_TEXT_VALID, bool(text))
        else:
            passed.append(GATE_TEXT_VALID)

        if policy.require_annotation:
            if has_active_annotation is None:
                has_active_annotation = SegmentAnnotation.objects.filter(
                    segment_id=segment.id,
                    removed_at__isnull=True,
                ).exists()
            gate(GATE_ANNOTATION_VALID, bool(has_active_annotation))
        else:
            passed.append(GATE_ANNOTATION_VALID)

        status = STATUS_READY if not failed else STATUS_NOT_READY
        return SegmentReadiness(
            segment_id=segment.id,
            status=status,
            failed_gates=tuple(failed),
            passed_gates=tuple(passed),
        )

    def evaluate_many(
        self,
        segments: Iterable[AudioSegment],
        *,
        project_id: uuid.UUID,
    ) -> dict[uuid.UUID, SegmentReadiness]:
        policy = self.policy_for_project(project_id)
        segment_list = list(segments)
        if not segment_list:
            return {}

        annotated_ids = set(
            SegmentAnnotation.objects.filter(
                segment_id__in=[s.id for s in segment_list],
                removed_at__isnull=True,
            ).values_list("segment_id", flat=True)
        )
        return {
            seg.id: self.evaluate(
                seg,
                policy=policy,
                has_active_annotation=seg.id in annotated_ids,
            )
            for seg in segment_list
        }

    def counts_for_project(self, project_id: uuid.UUID) -> ReadinessCounts:
        policy = self.policy_for_project(project_id)
        segments = list(
            AudioSegment.objects.filter(
                source__project_id=project_id,
                deleted_at__isnull=True,
            ).select_related("source", "current_artifact", "current_artifact__job")
        )
        if not segments:
            return ReadinessCounts()

        results = self.evaluate_many(segments, project_id=project_id)
        ready = 0
        need_review = 0
        need_transcript = 0
        need_annotation = 0
        need_artifact = 0
        failed_processing = 0

        for seg in segments:
            result = results[seg.id]
            if result.is_ready:
                ready += 1
            if GATE_REVIEW_OK in result.failed_gates:
                need_review += 1
            if GATE_TEXT_VALID in result.failed_gates:
                need_transcript += 1
            if GATE_ANNOTATION_VALID in result.failed_gates:
                need_annotation += 1
            if GATE_AUDIO_VALID in result.failed_gates:
                need_artifact += 1
            if seg.processing_status == AudioSegment.ProcessingStatus.FAILED:
                failed_processing += 1

        return ReadinessCounts(
            ready=ready,
            not_ready=len(segments) - ready,
            need_review=need_review if policy.require_audio_review else 0,
            need_transcript=need_transcript if policy.require_transcript else 0,
            need_annotation=need_annotation if policy.require_annotation else 0,
            need_artifact=need_artifact,
            failed_processing=failed_processing,
        )

    def filter_ready_queryset(self, qs, *, project_id: uuid.UUID):
        """Filter a segment queryset to those currently READY under project policy."""
        segments = list(
            qs.select_related("source", "current_artifact", "current_artifact__job")
        )
        results = self.evaluate_many(segments, project_id=project_id)
        ready_ids = [sid for sid, r in results.items() if r.is_ready]
        return qs.model.objects.filter(id__in=ready_ids).order_by(
            "source__created_at",
            "segment_index",
        )
