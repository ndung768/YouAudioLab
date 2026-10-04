"""Labels on a character span of the accepted transcript. No revision bump."""

from __future__ import annotations

import hashlib
import re
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
    TranscriptSpan,
)
from apps.workspace.services.membership import MembershipService

_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_TOKEN = re.compile(r"\S+|\s+")


def transcript_digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def tokenize_transcript(text: str) -> list[dict]:
    tokens: list[dict] = []
    for match in _TOKEN.finditer(text or ""):
        piece = match.group()
        tokens.append(
            {
                "text": piece,
                "start": match.start(),
                "end": match.end(),
                "is_word": not piece.isspace(),
            }
        )
    return tokens


def safe_label_color(value: str | None) -> str:
    if value and _COLOR.match(value.strip()):
        return value.strip()
    return "#d97706"


class TranscriptSpanService:
    def __init__(self) -> None:
        self.memberships = MembershipService()

    def mark_stale(self, segment_id: uuid.UUID) -> int:
        return TranscriptSpan.objects.filter(
            segment_id=segment_id,
            removed_at__isnull=True,
            stale=False,
        ).update(stale=True)

    def list_for_segment(
        self,
        segment_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        include_removed: bool = False,
        include_stale: bool = False,
        annotator_id: uuid.UUID | None = None,
    ) -> list[TranscriptSpan]:
        segment, project_id = self._segment_and_project(segment_id)
        self.memberships.require_member(project_id, actor_user_id)
        qs = (
            TranscriptSpan.objects.filter(segment_id=segment.id)
            .select_related("label__label", "annotator")
            .order_by("start_char", "end_char", "created_at")
        )
        if not include_removed:
            qs = qs.filter(removed_at__isnull=True)
        if not include_stale:
            qs = qs.filter(stale=False)
        if annotator_id is not None:
            qs = qs.filter(annotator_id=annotator_id)
        return list(qs)

    def decorate(
        self,
        text: str,
        spans: list[TranscriptSpan],
        *,
        actor_user_id: uuid.UUID,
        can_remove_any: bool,
    ) -> list[dict]:
        tokens = tokenize_transcript(text)
        active = [row for row in spans if row.removed_at is None and not row.stale]
        for token in tokens:
            token["span_id"] = ""
            token["color"] = ""
            token["title"] = ""
            if not token["is_word"]:
                continue
            covering = [
                row
                for row in active
                if row.start_char < token["end"] and row.end_char > token["start"]
            ]
            if not covering:
                continue
            covering.sort(key=lambda row: (row.end_char - row.start_char, row.created_at))
            names: list[str] = []
            for row in covering:
                name = row.label.display_name
                if name not in names:
                    names.append(name)
            removable = next(
                (
                    row
                    for row in covering
                    if can_remove_any or row.annotator_id == actor_user_id
                ),
                None,
            )
            token["title"] = ", ".join(names)
            if removable is not None:
                token["span_id"] = str(removable.id)
                token["color"] = safe_label_color(removable.label.display_color)
        return tokens

    def assign(
        self,
        *,
        segment_id: uuid.UUID,
        label_id: uuid.UUID | str,
        actor_user_id: uuid.UUID,
        start_char: int | str | None = None,
        end_char: int | str | None = None,
        quote: str | None = None,
    ) -> TranscriptSpan:
        segment, project_id = self._segment_and_project(segment_id)
        self.memberships.require_member(project_id, actor_user_id)
        self.memberships.require_active_project(project_id)
        if segment.deleted_at is not None:
            raise SegmentDeletedError(
                "Segment is soft-deleted",
                details={"segment_id": str(segment_id)},
            )
        label = self._assert_label_in_project(label_id, project_id)
        if not label.for_span:
            raise ValidationError(
                "This label is for the whole segment, not text in the transcript",
                details={"label_id": str(label_id), "code": "LABEL_SCOPE"},
            )
        text = segment.transcript or ""
        if not text.strip():
            raise ValidationError(
                "Need a transcript before labeling text",
                details={"segment_id": str(segment_id)},
            )
        start, end = self._resolve_offsets(
            text,
            start_char=start_char,
            end_char=end_char,
            quote=quote,
        )
        surface = text[start:end]
        if not surface.strip():
            raise ValidationError(
                "Text span is empty",
                details={"start_char": start, "end_char": end},
            )

        revision_before = segment.definition_revision
        existing = TranscriptSpan.objects.filter(
            segment_id=segment.id,
            label_id=label_id,
            annotator_id=actor_user_id,
            start_char=start,
            end_char=end,
            removed_at__isnull=True,
            stale=False,
        ).first()
        if existing is not None:
            self._assert_revision(segment, revision_before)
            return existing

        span = TranscriptSpan.objects.create(
            segment_id=segment.id,
            label_id=label_id,
            annotator_id=actor_user_id,
            start_char=start,
            end_char=end,
            quote=surface,
            transcript_sha256=transcript_digest(text),
        )
        self._assert_revision(segment, revision_before)
        return span

    def remove(
        self,
        span_id: uuid.UUID | str,
        *,
        actor_user_id: uuid.UUID,
    ) -> TranscriptSpan:
        try:
            span = TranscriptSpan.objects.select_related("segment").get(pk=span_id)
        except TranscriptSpan.DoesNotExist as exc:
            raise NotFoundError(
                "Text span not found",
                details={"span_id": str(span_id)},
            ) from exc
        segment, project_id = self._segment_and_project(span.segment_id)
        membership = self.memberships.require_member(project_id, actor_user_id)
        self.memberships.require_active_project(project_id)
        if segment.deleted_at is not None:
            raise SegmentDeletedError(
                "Segment is soft-deleted",
                details={"segment_id": str(segment.id)},
            )
        is_owner = membership.role == ProjectMembership.Role.OWNER
        if not is_owner and span.annotator_id != actor_user_id:
            raise ForbiddenError(
                "ANNOTATOR may only remove own text spans",
                details={"span_id": str(span_id)},
            )
        if span.removed_at is None:
            revision_before = segment.definition_revision
            span.removed_at = datetime.now(timezone.utc)
            span.removed_by_id = actor_user_id
            span.save(update_fields=["removed_at", "removed_by"])
            self._assert_revision(segment, revision_before)
        return span

    def _resolve_offsets(
        self,
        text: str,
        *,
        start_char: int | str | None,
        end_char: int | str | None,
        quote: str | None,
    ) -> tuple[int, int]:
        if start_char is not None or end_char is not None:
            start = self._int_field(start_char, "start_char")
            end = self._int_field(end_char, "end_char")
            if start < 0 or end > len(text) or end <= start:
                raise ValidationError(
                    "Text span is outside the transcript",
                    details={"start_char": start, "end_char": end, "length": len(text)},
                )
            return start, end
        needle = (quote or "").strip()
        if not needle:
            raise ValidationError(
                "Select text or type the exact word to label",
                details={"fields": [{"field": "quote", "code": "REQUIRED"}]},
            )
        start = text.find(needle)
        if start < 0:
            raise ValidationError(
                "That text is not in the transcript",
                details={"quote": needle},
            )
        if text.find(needle, start + 1) >= 0:
            raise ValidationError(
                "That text appears more than once. Select it in the transcript.",
                details={"quote": needle},
            )
        return start, start + len(needle)

    def _int_field(self, value: int | None, field: str) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Text span offsets must be integers",
                details={"fields": [{"field": field, "code": "INVALID"}]},
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
        if segment.source is None:
            raise NotFoundError(
                "Source not found for segment",
                details={"segment_id": str(segment_id)},
            )
        return segment, segment.source.project_id

    def _assert_label_in_project(
        self,
        label_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> ProjectLabel:
        row = ProjectLabel.objects.select_related("label").filter(pk=label_id).first()
        if row is None or row.project_id != project_id:
            raise NotFoundError(
                "Label not found",
                details={"label_id": str(label_id)},
            )
        return row

    def _assert_revision(self, segment: AudioSegment, revision_before: int) -> None:
        segment.refresh_from_db()
        if segment.definition_revision != revision_before:
            raise ValidationError(
                "Invariant violated: text span must not bump definition_revision",
                details={
                    "segment_id": str(segment.id),
                    "before": revision_before,
                    "after": segment.definition_revision,
                },
            )
