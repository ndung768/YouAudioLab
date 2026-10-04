"""AI assist service — cleanup / label / metadata candidates (W8.2–W8.3)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from django.db import transaction

from apps.core.errors import (
    NotFoundError,
    SegmentDeletedError,
    SegmentRevisionConflictError,
    ValidationError,
)
from apps.processing.models import AiAssistRun
from apps.processing.services.ai_ollama import AiProviderError, OllamaClient
from apps.processing.services.ai_resolve import resolve_ai_config
from apps.workspace.models import AudioSegment, VideoSource
from apps.workspace.services.annotation import AnnotationService
from apps.workspace.services.label import LabelService
from apps.workspace.services.membership import MembershipService

KIND_TRANSCRIPT_CLEANUP = "transcript_cleanup"
KIND_LABEL_SUGGEST = "label_suggest"
KIND_METADATA_SUGGEST = "metadata_suggest"
SUPPORTED_KINDS = frozenset(
    {KIND_TRANSCRIPT_CLEANUP, KIND_LABEL_SUGGEST, KIND_METADATA_SUGGEST}
)

PROMPT_CLEANUP = "cleanup-v1"
PROMPT_LABEL = "label-v1"
PROMPT_METADATA = "metadata-v1"

_CLEANUP_PROMPT = """You are a careful transcript editor for research audio datasets.
Clean up the transcript below:
- Fix obvious spelling/punctuation
- Keep the original language
- Do not invent content that was not said
- Do not add commentary, labels, or markdown
- Return ONLY the cleaned transcript text

Transcript:
"""

_LABEL_PROMPT = """You assign research labels from a fixed catalog.
Return ONLY valid JSON (no markdown) with this shape:
{{"suggestions":[{{"name":"<exact catalog name>","reason":"<short>"}}]}}

Rules:
- Choose zero or more labels from the catalog ONLY (exact name match)
- Prefer precision over recall
- Do not invent new label names

Catalog:
{catalog}

Transcript:
{transcript}
"""

_METADATA_PROMPT = """You extract lightweight research metadata from a transcript.
Return ONLY valid JSON (no markdown) with this shape:
{{"summary":"<1-3 sentences>","keywords":["..."],"language_hint":"<code or null>"}}

Rules:
- summary must stay faithful to the transcript
- keywords are short phrases (not full sentences)
- do not invent spoken content

Transcript:
{transcript}
"""


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text


def parse_assist_payload(kind: str, output_text: str) -> dict[str, Any]:
    if kind == KIND_TRANSCRIPT_CLEANUP:
        return {"text": output_text}
    try:
        data = json.loads(_strip_json_fence(output_text))
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "AI assist output is not valid JSON",
            details={"code": "AI_ASSIST_BAD_OUTPUT", "kind": kind},
        ) from exc
    if not isinstance(data, dict):
        raise ValidationError(
            "AI assist output must be a JSON object",
            details={"code": "AI_ASSIST_BAD_OUTPUT", "kind": kind},
        )
    return data


class AiAssistService:
    def __init__(
        self,
        *,
        ollama_factory: Callable[[str], OllamaClient] | None = None,
    ) -> None:
        self.memberships = MembershipService()
        self.labels = LabelService()
        self.annotations = AnnotationService()
        self._ollama_factory = ollama_factory or (lambda url: OllamaClient(base_url=url))

    def list_for_segment(self, segment_id: uuid.UUID) -> list[AiAssistRun]:
        return list(
            AiAssistRun.objects.filter(segment_id=segment_id).order_by("-created_at")
        )

    def get(self, assist_id: uuid.UUID) -> AiAssistRun:
        try:
            return AiAssistRun.objects.get(pk=assist_id)
        except AiAssistRun.DoesNotExist as exc:
            raise NotFoundError(
                "AI assist run not found",
                details={"assist_run_id": str(assist_id)},
            ) from exc

    def create(
        self,
        *,
        segment_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        expected_definition_revision: int,
        kind: str,
    ) -> AiAssistRun:
        kind_norm = (kind or "").strip().lower()
        if kind_norm not in SUPPORTED_KINDS:
            raise ValidationError(
                "Unsupported AI assist kind",
                details={
                    "fields": [
                        {
                            "field": "kind",
                            "code": "INVALID",
                            "allowed": sorted(SUPPORTED_KINDS),
                        }
                    ]
                },
            )
        if kind_norm == KIND_TRANSCRIPT_CLEANUP:
            return self.create_transcript_cleanup(
                segment_id=segment_id,
                actor_user_id=actor_user_id,
                expected_definition_revision=expected_definition_revision,
            )
        if kind_norm == KIND_LABEL_SUGGEST:
            return self.create_label_suggest(
                segment_id=segment_id,
                actor_user_id=actor_user_id,
                expected_definition_revision=expected_definition_revision,
            )
        return self.create_metadata_suggest(
            segment_id=segment_id,
            actor_user_id=actor_user_id,
            expected_definition_revision=expected_definition_revision,
        )

    def create_transcript_cleanup(
        self,
        *,
        segment_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        expected_definition_revision: int,
    ) -> AiAssistRun:
        segment, source = self._prepare_create(
            segment_id=segment_id,
            actor_user_id=actor_user_id,
            expected_definition_revision=expected_definition_revision,
        )
        input_text = self._require_transcript(segment)
        resolved = self._require_ai(actor_user_id, project_id=source.project_id)
        output = self._generate(
            resolved.ollama_base_url,
            resolved.ollama_model,
            _CLEANUP_PROMPT + input_text,
        )
        return self._persist_run(
            segment=segment,
            source=source,
            actor_user_id=actor_user_id,
            kind=KIND_TRANSCRIPT_CLEANUP,
            provider=resolved.provider,
            model=resolved.ollama_model,
            input_text=input_text,
            output_text=output.strip(),
            prompt_version=PROMPT_CLEANUP,
        )

    def create_label_suggest(
        self,
        *,
        segment_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        expected_definition_revision: int,
    ) -> AiAssistRun:
        segment, source = self._prepare_create(
            segment_id=segment_id,
            actor_user_id=actor_user_id,
            expected_definition_revision=expected_definition_revision,
        )
        input_text = self._require_transcript(segment)
        catalog = self.labels.list_for_project(source.project_id, scope="segment")
        if not catalog:
            raise ValidationError(
                "Project has no labels to suggest",
                details={"code": "AI_ASSIST_NO_LABELS"},
            )
        catalog_lines = "\n".join(f"- {lb.display_name}" for lb in catalog)
        resolved = self._require_ai(actor_user_id, project_id=source.project_id)
        prompt = _LABEL_PROMPT.format(catalog=catalog_lines, transcript=input_text)
        raw = self._generate(resolved.ollama_base_url, resolved.ollama_model, prompt)
        payload = parse_assist_payload(KIND_LABEL_SUGGEST, raw)
        suggestions = payload.get("suggestions")
        if not isinstance(suggestions, list):
            raise ValidationError(
                "label_suggest output missing suggestions list",
                details={"code": "AI_ASSIST_BAD_OUTPUT"},
            )
        allowed = {lb.display_name.casefold(): lb.display_name for lb in catalog}
        cleaned: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in suggestions:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            canonical = allowed.get(name.casefold())
            if canonical is None or canonical.casefold() in seen:
                continue
            seen.add(canonical.casefold())
            reason = str(item.get("reason") or "").strip()[:500]
            cleaned.append({"name": canonical, "reason": reason})
        output_text = json.dumps({"suggestions": cleaned}, ensure_ascii=False)
        return self._persist_run(
            segment=segment,
            source=source,
            actor_user_id=actor_user_id,
            kind=KIND_LABEL_SUGGEST,
            provider=resolved.provider,
            model=resolved.ollama_model,
            input_text=input_text,
            output_text=output_text,
            prompt_version=PROMPT_LABEL,
        )

    def create_metadata_suggest(
        self,
        *,
        segment_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        expected_definition_revision: int,
    ) -> AiAssistRun:
        segment, source = self._prepare_create(
            segment_id=segment_id,
            actor_user_id=actor_user_id,
            expected_definition_revision=expected_definition_revision,
        )
        input_text = self._require_transcript(segment)
        resolved = self._require_ai(actor_user_id, project_id=source.project_id)
        prompt = _METADATA_PROMPT.format(transcript=input_text)
        raw = self._generate(resolved.ollama_base_url, resolved.ollama_model, prompt)
        payload = parse_assist_payload(KIND_METADATA_SUGGEST, raw)
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            raise ValidationError(
                "metadata_suggest output missing summary",
                details={"code": "AI_ASSIST_BAD_OUTPUT"},
            )
        keywords_raw = payload.get("keywords") or []
        keywords: list[str] = []
        if isinstance(keywords_raw, list):
            for kw in keywords_raw:
                text = str(kw).strip()
                if text and text.casefold() not in {k.casefold() for k in keywords}:
                    keywords.append(text[:120])
        language_hint = payload.get("language_hint")
        language = (
            str(language_hint).strip()[:32]
            if language_hint is not None and str(language_hint).strip()
            else None
        )
        catalog = self.labels.list_for_project(source.project_id, scope="segment")
        allowed = {lb.display_name.casefold(): lb.display_name for lb in catalog}
        matched_labels = [
            allowed[k.casefold()] for k in keywords if k.casefold() in allowed
        ]
        output_text = json.dumps(
            {
                "summary": summary[:4000],
                "keywords": keywords[:40],
                "language_hint": language,
                "matched_label_names": matched_labels,
            },
            ensure_ascii=False,
        )
        return self._persist_run(
            segment=segment,
            source=source,
            actor_user_id=actor_user_id,
            kind=KIND_METADATA_SUGGEST,
            provider=resolved.provider,
            model=resolved.ollama_model,
            input_text=input_text,
            output_text=output_text,
            prompt_version=PROMPT_METADATA,
        )

    def apply(
        self,
        assist_id: uuid.UUID,
        *,
        expected_definition_revision: int,
        actor_user_id: uuid.UUID,
    ) -> AudioSegment:
        run = self.get(assist_id)
        self.memberships.require_owner(run.project_id, actor_user_id)
        self.memberships.require_active_project(run.project_id)

        with transaction.atomic():
            segment = (
                AudioSegment.objects.select_for_update()
                .filter(pk=run.segment_id)
                .first()
            )
            if segment is None:
                raise NotFoundError(
                    "Segment not found",
                    details={"segment_id": str(run.segment_id)},
                )
            if segment.deleted_at is not None:
                raise SegmentDeletedError(
                    "Segment is soft-deleted",
                    details={"segment_id": str(segment.id)},
                )
            if segment.definition_revision != expected_definition_revision:
                raise SegmentRevisionConflictError(
                    "Segment definition_revision conflict",
                    details={
                        "segment_id": str(segment.id),
                        "current_definition_revision": segment.definition_revision,
                        "expected_definition_revision": expected_definition_revision,
                    },
                )
            if run.segment_revision != segment.definition_revision:
                raise ValidationError(
                    "AI assist run is stale for current segment revision",
                    details={
                        "code": "AI_ASSIST_STALE",
                        "assist_run_id": str(run.id),
                        "run_segment_revision": run.segment_revision,
                        "definition_revision": segment.definition_revision,
                    },
                )
            if run.applied_at is not None:
                raise ValidationError(
                    "AI assist run was already applied",
                    details={
                        "code": "AI_ASSIST_ALREADY_APPLIED",
                        "assist_run_id": str(run.id),
                    },
                )

            if run.kind == KIND_TRANSCRIPT_CLEANUP:
                previous = segment.transcript or ""
                segment.transcript = run.output_text
                segment.save(update_fields=["transcript", "updated_at"])
                if previous != (segment.transcript or ""):
                    from apps.workspace.services.transcript_span import TranscriptSpanService

                    TranscriptSpanService().mark_stale(segment.id)
            elif run.kind == KIND_LABEL_SUGGEST:
                self._apply_label_names(
                    segment_id=segment.id,
                    actor_user_id=actor_user_id,
                    project_id=run.project_id,
                    names=self._names_from_label_payload(run.output_text),
                )
            elif run.kind == KIND_METADATA_SUGGEST:
                payload = parse_assist_payload(KIND_METADATA_SUGGEST, run.output_text)
                matched = payload.get("matched_label_names") or []
                names = [str(n).strip() for n in matched if str(n).strip()]
                if not names:
                    raise ValidationError(
                        "No catalog-matched labels to apply from metadata assist",
                        details={"code": "AI_ASSIST_NO_MATCHED_LABELS"},
                    )
                self._apply_label_names(
                    segment_id=segment.id,
                    actor_user_id=actor_user_id,
                    project_id=run.project_id,
                    names=names,
                )
            else:
                raise ValidationError(
                    "Unsupported AI assist kind",
                    details={"code": "AI_ASSIST_BAD_KIND", "kind": run.kind},
                )

            run.applied_at = datetime.now(timezone.utc)
            run.save(update_fields=["applied_at"])
        return segment

    def _apply_label_names(
        self,
        *,
        segment_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        project_id: uuid.UUID,
        names: list[str],
    ) -> None:
        if not names:
            raise ValidationError(
                "No labels to apply",
                details={"code": "AI_ASSIST_EMPTY_LABELS"},
            )
        for name in names:
            label = self.labels.find_by_name_ci(project_id, name)
            if label is None or not label.for_segment:
                continue
            self.annotations.assign(
                segment_id=segment_id,
                label_id=label.id,
                actor_user_id=actor_user_id,
            )

    def _names_from_label_payload(self, output_text: str) -> list[str]:
        payload = parse_assist_payload(KIND_LABEL_SUGGEST, output_text)
        suggestions = payload.get("suggestions") or []
        names: list[str] = []
        if isinstance(suggestions, list):
            for item in suggestions:
                if isinstance(item, dict) and item.get("name"):
                    names.append(str(item["name"]).strip())
        return names

    def _prepare_create(
        self,
        *,
        segment_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        expected_definition_revision: int,
    ) -> tuple[AudioSegment, VideoSource]:
        segment, source = self._load_segment_context(segment_id)
        self.memberships.require_owner(source.project_id, actor_user_id)
        self.memberships.require_active_project(source.project_id)
        if segment.deleted_at is not None:
            raise SegmentDeletedError(
                "Segment is soft-deleted",
                details={"segment_id": str(segment_id)},
            )
        if segment.definition_revision != expected_definition_revision:
            raise SegmentRevisionConflictError(
                "Segment definition_revision conflict",
                details={
                    "segment_id": str(segment_id),
                    "current_definition_revision": segment.definition_revision,
                    "expected_definition_revision": expected_definition_revision,
                },
            )
        return segment, source

    def _require_transcript(self, segment: AudioSegment) -> str:
        input_text = (segment.transcript or "").strip()
        if not input_text:
            raise ValidationError(
                "Segment has no transcript for AI assist",
                details={
                    "fields": [{"field": "transcript", "code": "REQUIRED"}],
                    "code": "AI_ASSIST_NO_TRANSCRIPT",
                },
            )
        return input_text

    def _require_ai(self, actor_user_id: uuid.UUID, *, project_id: uuid.UUID):
        resolved = resolve_ai_config(
            actor_user_id=actor_user_id, project_id=project_id
        )
        if not resolved.enabled:
            raise ValidationError(
                "AI provider is disabled",
                details={"code": "AI_PROVIDER_DISABLED"},
            )
        return resolved

    def _generate(self, base_url: str, model: str, prompt: str) -> str:
        client = self._ollama_factory(base_url)
        try:
            return client.generate(model=model, prompt=prompt)
        except AiProviderError as exc:
            raise ValidationError(
                exc.message,
                details={"code": exc.code},
            ) from exc

    def _persist_run(
        self,
        *,
        segment: AudioSegment,
        source: VideoSource,
        actor_user_id: uuid.UUID,
        kind: str,
        provider: str,
        model: str,
        input_text: str,
        output_text: str,
        prompt_version: str,
    ) -> AiAssistRun:
        now = datetime.now(timezone.utc)
        return AiAssistRun.objects.create(
            segment=segment,
            project_id=source.project_id,
            source=source,
            created_by_user_id=actor_user_id,
            kind=kind,
            provider=provider,
            model=model,
            segment_revision=segment.definition_revision,
            input_text=input_text,
            output_text=output_text,
            prompt_version=prompt_version,
            completed_at=now,
        )

    def _load_segment_context(
        self, segment_id: uuid.UUID
    ) -> tuple[AudioSegment, VideoSource]:
        try:
            segment = AudioSegment.objects.select_related("source").get(pk=segment_id)
        except AudioSegment.DoesNotExist as exc:
            raise NotFoundError(
                "Segment not found",
                details={"segment_id": str(segment_id)},
            ) from exc
        return segment, segment.source
