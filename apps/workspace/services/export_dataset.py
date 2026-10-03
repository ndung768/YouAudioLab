"""Research dataset export. Read-only. Segment is the unit; formats are views of one snapshot."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from apps.core.errors import ValidationError
from apps.processing.models import AiAssistRun, AsrRun, ProcessingArtifact
from apps.workspace.models import (
    AnnotationAssignment,
    AudioSegment,
    Project,
    ProjectLabel,
    ProjectMembership,
    ProjectSettings,
    SegmentAnnotation,
    SegmentGoldLabel,
    VideoSource,
)
from apps.workspace.services.membership import MembershipService

SCHEMA = "youaudiolab.research_dataset"
SCHEMA_VERSION = "1.1"
SUPERVISION_POLICIES = frozenset(
    {"union", "majority", "intersection", "first_annotator", "gold"}
)
SPLIT_STRATEGIES = frozenset({"none", "by_source"})


@dataclass(frozen=True)
class ExportFormat:
    key: str
    label: str
    group: str
    extension: str
    content_type: str
    description: str


FORMATS: dict[str, ExportFormat] = {
    "json": ExportFormat(
        "json",
        "JSON — research snapshot",
        "Research",
        ".json",
        "application/json",
        "Full snapshot: segment, annotations, assignments, ASR runs, AI assists.",
    ),
    "jsonl": ExportFormat(
        "jsonl",
        "JSONL — one segment per line",
        "Research",
        ".jsonl",
        "application/jsonl",
        "Same segment records as the research JSON, streamed one object per line.",
    ),
    "json_segments": ExportFormat(
        "json_segments",
        "JSON — segment classification",
        "General",
        ".json",
        "application/json",
        "One object per segment with canonical transcript and active labels.",
    ),
    "xml": ExportFormat(
        "xml",
        "XML — corpus",
        "General",
        ".xml",
        "application/xml",
        "Segment tree with transcript, labels, and annotators.",
    ),
    "csv_segments": ExportFormat(
        "csv_segments",
        "CSV — one row per segment",
        "Spreadsheet",
        ".csv",
        "text/csv; charset=utf-8",
        "UTF-8 with BOM so Excel opens Vietnamese text correctly.",
    ),
    "csv_annotations": ExportFormat(
        "csv_annotations",
        "CSV — one row per annotation (IAA)",
        "Spreadsheet",
        ".csv",
        "text/csv; charset=utf-8",
        "One human decision per row. Use this to recompute agreement.",
    ),
    "csv_assignments": ExportFormat(
        "csv_assignments",
        "CSV — one row per assignment",
        "Spreadsheet",
        ".csv",
        "text/csv; charset=utf-8",
        "Work-queue rows. Separate from labels.",
    ),
    "xlsx": ExportFormat(
        "xlsx",
        "Excel — segments, annotations, assignments, ASR",
        "Spreadsheet",
        ".xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Workbook for review. Large projects should use CSV.",
    ),
    "doccano_jsonl": ExportFormat(
        "doccano_jsonl",
        "Doccano JSONL — text classification",
        "Other tools",
        ".jsonl",
        "application/jsonl",
        "Transcript plus active label names. No token spans; this corpus is segment-level.",
    ),
    "label_studio_json": ExportFormat(
        "label_studio_json",
        "Label Studio — text labels",
        "Other tools",
        ".json",
        "application/json",
        "Pre-annotations as choices on the transcript.",
    ),
    "hf_jsonl": ExportFormat(
        "hf_jsonl",
        "HuggingFace JSONL — text classification",
        "Training",
        ".jsonl",
        "application/jsonl",
        "First line is label metadata. Following lines are text plus label names.",
    ),
    "spacy_json": ExportFormat(
        "spacy_json",
        "spaCy JSON — document categories",
        "Training",
        ".json",
        "application/json",
        "Text classification cats. Entity spans are empty because labels apply to the whole segment.",
    ),
    "json_llm": ExportFormat(
        "json_llm",
        "JSONL — LLM messages",
        "Training",
        ".jsonl",
        "application/jsonl",
        "system/user/assistant messages. Active labels only.",
    ),
    "dataset_zip": ExportFormat(
        "dataset_zip",
        "ZIP — audio + metadata + README",
        "Research",
        ".zip",
        "application/zip",
        "audio/ files from current verified artifacts, CSV metadata, and README.md.",
    ),
}


def format_groups() -> list[tuple[str, list[ExportFormat]]]:
    order: list[str] = []
    grouped: dict[str, list[ExportFormat]] = {}
    for item in FORMATS.values():
        if item.group not in grouped:
            order.append(item.group)
            grouped[item.group] = []
        grouped[item.group].append(item)
    return [(name, grouped[name]) for name in order]


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _active_episodes(segment: dict) -> list[dict]:
    return [row for row in segment.get("annotations") or [] if row.get("removed_at") is None]


def _active_labels(segment: dict) -> list[str]:
    names: list[str] = []
    for row in _active_episodes(segment):
        if row["label"] not in names:
            names.append(row["label"])
    return names


def _supervised_labels(segment: dict, policy: str) -> list[str]:
    """Collapse active episodes to a label list for training views."""
    policy = (policy or "majority").strip().lower()
    if policy not in SUPERVISION_POLICIES:
        raise ValidationError(
            "Unknown supervision policy",
            details={"fields": [{"field": "supervision_policy", "code": "INVALID"}]},
        )
    if policy == "gold":
        gold = list(segment.get("gold_labels") or [])
        if gold:
            return gold
    episodes = _active_episodes(segment)
    if not episodes:
        return []
    if policy == "union":
        return _active_labels(segment)

    by_annotator: dict[str, set[str]] = {}
    first_id: str | None = None
    first_at: str | None = None
    for row in episodes:
        aid = str(row.get("annotator_id") or "")
        by_annotator.setdefault(aid, set()).add(row["label"])
        created = row.get("created_at") or ""
        if first_at is None or created < first_at:
            first_at = created
            first_id = aid

    annotators = [aid for aid in by_annotator if aid]
    if not annotators:
        return _active_labels(segment)

    if policy == "first_annotator":
        ordered: list[str] = []
        for row in episodes:
            if str(row.get("annotator_id") or "") == first_id and row["label"] not in ordered:
                ordered.append(row["label"])
        return ordered

    if policy == "intersection":
        common = set.intersection(*(by_annotator[aid] for aid in annotators))
        return [name for name in _active_labels(segment) if name in common]

    n = len(annotators)
    threshold = n // 2 + 1  # strict majority (> half)
    counts: dict[str, int] = {}
    for aid in annotators:
        for name in by_annotator[aid]:
            counts[name] = counts.get(name, 0) + 1
    return [name for name in _active_labels(segment) if counts.get(name, 0) >= threshold]


def _assign_splits(
    segments: list[dict],
    *,
    strategy: str,
    seed: int,
    train: float,
    val: float,
    test: float,
) -> tuple[dict, list[str]]:
    """Attach segment['split']; return (split meta, warnings)."""
    strategy = (strategy or "by_source").strip().lower()
    if strategy not in SPLIT_STRATEGIES:
        raise ValidationError(
            "Unknown split strategy",
            details={"fields": [{"field": "split_strategy", "code": "INVALID"}]},
        )
    warnings: list[str] = []
    ratios = {"train": float(train), "val": float(val), "test": float(test)}
    total = ratios["train"] + ratios["val"] + ratios["test"]
    if abs(total - 1.0) > 1e-6:
        raise ValidationError(
            "Split ratios must sum to 1.0",
            details={"fields": [{"field": "split_ratios", "code": "INVALID"}]},
        )

    meta = {
        "strategy": strategy,
        "seed": int(seed),
        "ratios": ratios,
        "group_by": "source_id" if strategy == "by_source" else None,
    }

    if strategy == "none" or not segments:
        for segment in segments:
            segment["split"] = None
        return meta, warnings

    source_ids = sorted({segment["source_id"] for segment in segments})
    rng = random.Random(int(seed))
    shuffled = list(source_ids)
    rng.shuffle(shuffled)

    if len(shuffled) == 1:
        warnings.append(
            "Only one source in export; all segments assigned to train "
            "(by_source cannot produce a non-degenerate holdout)."
        )
        assignment = {shuffled[0]: "train"}
    else:
        n = len(shuffled)
        n_train = int(n * ratios["train"])
        n_val = int(n * ratios["val"])
        if n_train == 0 and n >= 1:
            n_train = 1
        if n_val == 0 and ratios["val"] > 0 and n - n_train >= 2:
            n_val = 1
        n_test = n - n_train - n_val
        if n_test < 0:
            n_val = max(0, n_val + n_test)
            n_test = n - n_train - n_val
        if n_test == 0 and ratios["test"] > 0 and n_train > 1:
            n_train -= 1
            n_test = 1
        buckets = ["train"] * n_train + ["val"] * n_val + ["test"] * n_test
        while len(buckets) < n:
            buckets.append("train")
        buckets = buckets[:n]
        assignment = {sid: buckets[i] for i, sid in enumerate(shuffled)}
        if "test" not in assignment.values() and ratios["test"] > 0 and n >= 2:
            assignment[shuffled[-1]] = "test"
            warnings.append("Adjusted assignment so at least one source is in test.")

    for segment in segments:
        segment["split"] = assignment.get(segment["source_id"], "train")
    return meta, warnings


def _strip_storage_keys(snapshot: dict) -> None:
    for segment in snapshot.get("segments") or []:
        artifact = segment.get("current_artifact")
        if isinstance(artifact, dict):
            artifact.pop("storage_key", None)


def _content_hash(snapshot: dict) -> str:
    payload = {
        "project": snapshot.get("project"),
        "settings": snapshot.get("settings"),
        "label_set": snapshot.get("label_set"),
        "sources": snapshot.get("sources"),
        "segments": snapshot.get("segments"),
        "ready_only": snapshot.get("ready_only"),
        "split": snapshot.get("split"),
        "supervision_policy": snapshot.get("supervision_policy"),
        "users": snapshot.get("users"),
        "counts": snapshot.get("counts"),
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _labels_for_training(snapshot: dict, segment: dict) -> list[str]:
    if "supervised_labels" in segment:
        return list(segment["supervised_labels"])
    policy = snapshot.get("supervision_policy") or "majority"
    return _supervised_labels(segment, policy)


class ExportService:
    def __init__(self) -> None:
        self.memberships = MembershipService()

    def build_snapshot(
        self,
        project_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        source_id: uuid.UUID | None = None,
        include_deleted_segments: bool = False,
        include_removed_annotations: bool = True,
        include_released_assignments: bool = True,
        include_stale_asr: bool = True,
        ready_only: bool = False,
        split_strategy: str = "by_source",
        split_seed: int = 42,
        split_train: float = 0.8,
        split_val: float = 0.1,
        split_test: float = 0.1,
        supervision_policy: str = "majority",
    ) -> dict:
        self.memberships.require_owner(project_id, actor_user_id)
        project = Project.objects.filter(pk=project_id).first()
        if project is None:
            from apps.core.errors import NotFoundError

            raise NotFoundError("Project not found", details={"project_id": str(project_id)})

        supervision_policy = (supervision_policy or "majority").strip().lower()
        if supervision_policy not in SUPERVISION_POLICIES:
            raise ValidationError(
                "Unknown supervision policy",
                details={"fields": [{"field": "supervision_policy", "code": "INVALID"}]},
            )

        sources = VideoSource.objects.filter(project_id=project_id).order_by("created_at")
        if source_id is not None:
            sources = sources.filter(pk=source_id)
        source_list = list(sources)

        segments_qs = AudioSegment.objects.filter(source__project_id=project_id).select_related(
            "source",
            "current_artifact",
            "current_artifact__job",
            "audio_reviewed_by",
        )
        if source_id is not None:
            segments_qs = segments_qs.filter(source_id=source_id)
        if not include_deleted_segments:
            segments_qs = segments_qs.filter(deleted_at__isnull=True)
        segments = list(segments_qs.order_by("source__created_at", "segment_index"))

        if ready_only:
            from apps.workspace.services.readiness import ReadinessService

            readiness_map = ReadinessService().evaluate_many(segments, project_id=project_id)
            segments = [s for s in segments if readiness_map[s.id].is_ready]

        segment_ids = [segment.id for segment in segments]

        labels = list(
            ProjectLabel.objects.filter(project_id=project_id)
            .select_related("label")
            .order_by("sort_order", "id")
        )
        annotations = list(
            SegmentAnnotation.objects.filter(segment_id__in=segment_ids)
            .select_related("label__label", "annotator")
            .order_by("created_at")
        )
        if not include_removed_annotations:
            annotations = [row for row in annotations if row.removed_at is None]

        assignments = list(
            AnnotationAssignment.objects.filter(segment_id__in=segment_ids)
            .select_related("assignee", "assigned_by")
            .order_by("created_at")
        )
        if not include_released_assignments:
            assignments = [
                row
                for row in assignments
                if row.status != AnnotationAssignment.Status.RELEASED
            ]

        asr_runs = list(
            AsrRun.objects.filter(segment_id__in=segment_ids).order_by("created_at")
        )
        if not include_stale_asr:
            asr_runs = [row for row in asr_runs if not row.is_stale_result]

        assists = list(
            AiAssistRun.objects.filter(segment_id__in=segment_ids).order_by("created_at")
        )

        by_segment_ann: dict[uuid.UUID, list] = {}
        by_segment_asg: dict[uuid.UUID, list] = {}
        by_segment_asr: dict[uuid.UUID, list] = {}
        by_segment_ai: dict[uuid.UUID, list] = {}
        for row in annotations:
            by_segment_ann.setdefault(row.segment_id, []).append(row)
        for row in assignments:
            by_segment_asg.setdefault(row.segment_id, []).append(row)
        for row in asr_runs:
            by_segment_asr.setdefault(row.segment_id, []).append(row)
        for row in assists:
            by_segment_ai.setdefault(row.segment_id, []).append(row)

        gold_rows = list(
            SegmentGoldLabel.objects.filter(segment_id__in=segment_ids)
            .select_related("label__label", "adjudicated_by")
            .order_by("created_at")
        )
        by_segment_gold: dict[uuid.UUID, list] = {}
        for row in gold_rows:
            by_segment_gold.setdefault(row.segment_id, []).append(row)

        user_ids: dict[uuid.UUID, str] = {}
        roles = {
            row.user_id: row.role
            for row in ProjectMembership.objects.filter(
                project_id=project_id,
                revoked_at__isnull=True,
            )
        }

        def remember(user) -> str | None:
            if user is None:
                return None
            user_ids[user.id] = user.display_name
            return str(user.id)

        segment_payloads = []
        for segment in segments:
            artifact = segment.current_artifact
            youtube_id = segment.source.youtube_video_id or ""
            segment_key = (
                f"{youtube_id}#{segment.segment_index}"
                if youtube_id
                else f"#{segment.segment_index}"
            )
            segment_payloads.append(
                {
                    "segment_id": str(segment.id),
                    "segment_key": segment_key,
                    "source_id": str(segment.source_id),
                    "youtube_video_id": youtube_id,
                    "segment_index": segment.segment_index,
                    "start_seconds": segment.start_seconds,
                    "end_seconds": segment.end_seconds,
                    "duration_seconds": segment.duration_seconds,
                    "definition_revision": segment.definition_revision,
                    "transcript": segment.transcript or "",
                    "processing_status": segment.processing_status,
                    "audio_reviewed_at": _iso(segment.audio_reviewed_at),
                    "audio_reviewed_by_id": (
                        str(segment.audio_reviewed_by_id)
                        if segment.audio_reviewed_by_id
                        else None
                    ),
                    "deleted_at": _iso(segment.deleted_at),
                    "current_artifact": None
                    if artifact is None
                    else {
                        "artifact_id": str(artifact.id),
                        "format": artifact.format,
                        "sample_rate_hz": artifact.sample_rate_hz,
                        "channels": artifact.channels,
                        "file_size_bytes": artifact.file_size_bytes,
                        "checksum": artifact.checksum,
                        "verified": artifact.verified,
                        "created_at": _iso(artifact.created_at),
                    },
                    "current_asr_run_id": str(segment.current_asr_run_id)
                    if segment.current_asr_run_id
                    else None,
                    "annotations": [
                        {
                            "annotation_id": str(row.id),
                            "project_label_id": str(row.label_id),
                            "label": row.label.display_name,
                            "annotator_id": remember(row.annotator),
                            "annotator": row.annotator.display_name,
                            "created_at": _iso(row.created_at),
                            "removed_at": _iso(row.removed_at),
                            "removed_by_id": remember(row.removed_by),
                        }
                        for row in by_segment_ann.get(segment.id, [])
                    ],
                    "assignments": [
                        {
                            "assignment_id": str(row.id),
                            "assignee_id": remember(row.assignee),
                            "assignee": row.assignee.display_name,
                            "assigned_by_id": remember(row.assigned_by),
                            "assignment_group_id": str(row.assignment_group_id),
                            "batch_id": str(row.batch_id) if row.batch_id else None,
                            "status": row.status,
                            "priority": row.priority,
                            "created_at": _iso(row.created_at),
                            "started_at": _iso(row.started_at),
                            "completed_at": _iso(row.completed_at),
                            "released_at": _iso(row.released_at),
                        }
                        for row in by_segment_asg.get(segment.id, [])
                    ],
                    "asr_runs": [
                        {
                            "asr_run_id": str(row.id),
                            "segment_revision": row.segment_revision,
                            "is_stale_result": row.is_stale_result,
                            "aligned": (
                                row.segment_revision == segment.definition_revision
                                and not row.is_stale_result
                            ),
                            "provider": row.provider,
                            "engine": row.engine,
                            "model": row.model,
                            "language_requested": row.language_requested,
                            "language_detected": row.language_detected,
                            "text": row.text,
                            "artifact_id": str(row.artifact_id),
                            "artifact_checksum": row.artifact_checksum,
                            "created_at": _iso(row.created_at),
                            "completed_at": _iso(row.completed_at),
                        }
                        for row in by_segment_asr.get(segment.id, [])
                    ],
                    "gold_labels": [
                        row.label.display_name
                        for row in by_segment_gold.get(segment.id, [])
                    ],
                    "gold": [
                        {
                            "project_label_id": str(row.label_id),
                            "label": row.label.display_name,
                            "adjudicated_by_id": remember(row.adjudicated_by),
                            "created_at": _iso(row.created_at),
                        }
                        for row in by_segment_gold.get(segment.id, [])
                    ],
                    "ai_assists": [
                        {
                            "assist_run_id": str(row.id),
                            "kind": row.kind,
                            "provider": row.provider,
                            "model": row.model,
                            "prompt_version": row.prompt_version,
                            "segment_revision": row.segment_revision,
                            "input_text": row.input_text,
                            "output_text": row.output_text,
                            "created_by_user_id": remember(row.created_by_user),
                            "created_at": _iso(row.created_at),
                            "completed_at": _iso(row.completed_at),
                            "applied_at": _iso(row.applied_at),
                        }
                        for row in by_segment_ai.get(segment.id, [])
                    ],
                }
            )

        split_meta, split_warnings = _assign_splits(
            segment_payloads,
            strategy=split_strategy,
            seed=split_seed,
            train=split_train,
            val=split_val,
            test=split_test,
        )
        for segment in segment_payloads:
            segment["supervised_labels"] = _supervised_labels(segment, supervision_policy)

        exported_at = datetime.now(timezone.utc).isoformat()
        try:
            settings = project.settings
            settings_payload = {
                "output_format": settings.output_format,
                "encoding": settings.encoding,
                "sample_rate_hz": settings.sample_rate_hz,
                "channels": settings.channels,
                "loudness_normalization": settings.loudness_normalization,
                "require_audio_review": settings.require_audio_review,
                "require_transcript": settings.require_transcript,
                "require_annotation": settings.require_annotation,
                "blind_annotators": settings.blind_annotators,
            }
        except ProjectSettings.DoesNotExist:
            settings_payload = {}

        snapshot = {
            "export_schema": SCHEMA,
            "export_schema_version": SCHEMA_VERSION,
            "exported_at": exported_at,
            "ready_only": ready_only,
            "split": split_meta,
            "supervision_policy": supervision_policy,
            "project": {
                "project_id": str(project.id),
                "name": project.name,
                "description": project.description,
                "language": project.language,
                "status": project.status,
                "license": project.license,
                "consent_notes": project.consent_notes,
            },
            "settings": settings_payload,
            "label_set": [
                {
                    "project_label_id": str(row.id),
                    "canonical_label_id": str(row.label_id),
                    "name": row.display_name,
                    "catalog_name": row.label.name,
                    "description": row.display_description,
                    "include_guidance": row.display_include_guidance,
                    "exclude_guidance": row.display_exclude_guidance,
                    "color": row.display_color,
                    "catalog_is_active": row.label.is_active,
                }
                for row in labels
            ],
            "sources": [
                {
                    "source_id": str(row.id),
                    "youtube_video_id": row.youtube_video_id,
                    "youtube_url": row.youtube_url,
                    "title": row.title,
                    "channel_name": row.channel_name,
                    "duration_seconds": row.duration_seconds,
                    "source_status": row.source_status,
                }
                for row in source_list
            ],
            "segments": segment_payloads,
            "users": [
                {
                    "user_id": str(user_id),
                    "display_name": name,
                    "role": roles.get(user_id),
                }
                for user_id, name in sorted(user_ids.items(), key=lambda item: item[1])
            ],
            "counts": {
                "sources": len(source_list),
                "segments": len(segment_payloads),
                "annotations": sum(len(row["annotations"]) for row in segment_payloads),
                "assignments": sum(len(row["assignments"]) for row in segment_payloads),
                "asr_runs": sum(len(row["asr_runs"]) for row in segment_payloads),
            },
        }
        if split_warnings:
            snapshot["split_warnings"] = split_warnings
        _strip_storage_keys(snapshot)
        digest = _content_hash(snapshot)
        snapshot["content_hash"] = digest
        snapshot["dataset_version"] = f"yal-{digest[:12]}"
        return snapshot

    def render(self, snapshot: dict, export_format: str) -> tuple[bytes, ExportFormat]:
        meta = FORMATS.get(export_format)
        if meta is None:
            raise ValidationError(
                "Unknown export format",
                details={"format": export_format},
            )
        renderer = _RENDERERS[export_format]
        return renderer(snapshot), meta

def _json_bytes(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _render_json(snapshot: dict) -> bytes:
    return _json_bytes(snapshot)


def _render_jsonl(snapshot: dict) -> bytes:
    lines = [json.dumps(row, ensure_ascii=False) for row in snapshot["segments"]]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _segment_brief(snapshot: dict, segment: dict) -> dict:
    return {
        "id": segment["segment_id"],
        "source_id": segment["source_id"],
        "segment_index": segment["segment_index"],
        "start_seconds": segment["start_seconds"],
        "end_seconds": segment["end_seconds"],
        "text": segment["transcript"],
        "definition_revision": segment["definition_revision"],
        "split": segment.get("split"),
        "labels": _labels_for_training(snapshot, segment),
        "annotators": [
            {"annotator_id": row["annotator_id"], "annotator": row["annotator"], "label": row["label"]}
            for row in segment["annotations"]
            if row["removed_at"] is None
        ],
    }


def _render_json_segments(snapshot: dict) -> bytes:
    return _json_bytes([_segment_brief(snapshot, row) for row in snapshot["segments"]])


def _csv_bytes(headers: list[str], rows: list[list]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _render_csv_segments(snapshot: dict) -> bytes:
    rows = []
    for segment in snapshot["segments"]:
        rows.append(
            [
                segment.get("segment_key") or "",
                segment["segment_index"],
                segment.get("youtube_video_id") or "",
                segment["start_seconds"],
                segment["end_seconds"],
                segment["definition_revision"],
                segment["transcript"],
                "|".join(_labels_for_training(snapshot, segment)),
                segment.get("split") or "",
                segment["processing_status"],
                segment["deleted_at"] or "",
                segment["segment_id"],
                segment["source_id"],
            ]
        )
    return _csv_bytes(
        [
            "segment_key",
            "segment_index",
            "youtube_video_id",
            "start_seconds",
            "end_seconds",
            "definition_revision",
            "transcript",
            "labels",
            "split",
            "processing_status",
            "deleted_at",
            "segment_id",
            "source_id",
        ],
        rows,
    )


def _render_csv_annotations(snapshot: dict) -> bytes:
    rows = []
    for segment in snapshot["segments"]:
        for row in segment["annotations"]:
            rows.append(
                [
                    segment.get("segment_key") or "",
                    segment["segment_index"],
                    segment.get("split") or "",
                    segment["transcript"],
                    row["annotator"],
                    row["label"],
                    row["created_at"],
                    row["removed_at"] or "",
                    segment["segment_id"],
                    row["annotation_id"],
                    row["annotator_id"],
                    row["project_label_id"],
                ]
            )
    return _csv_bytes(
        [
            "segment_key",
            "segment_index",
            "split",
            "transcript",
            "annotator",
            "label",
            "created_at",
            "removed_at",
            "segment_id",
            "annotation_id",
            "annotator_id",
            "project_label_id",
        ],
        rows,
    )


def _render_csv_assignments(snapshot: dict) -> bytes:
    rows = []
    for segment in snapshot["segments"]:
        for row in segment["assignments"]:
            rows.append(
                [
                    segment.get("segment_key") or "",
                    segment["segment_index"],
                    row["assignee"],
                    row["status"],
                    row["created_at"],
                    row["completed_at"] or "",
                    row["released_at"] or "",
                    segment["segment_id"],
                    row["assignment_id"],
                    row["assignee_id"],
                    row["assignment_group_id"],
                ]
            )
    return _csv_bytes(
        [
            "segment_key",
            "segment_index",
            "assignee",
            "status",
            "created_at",
            "completed_at",
            "released_at",
            "segment_id",
            "assignment_id",
            "assignee_id",
            "assignment_group_id",
        ],
        rows,
    )


def _xml_text(value) -> str:
    return escape("" if value is None else str(value))


def _render_xml(snapshot: dict) -> bytes:
    project = snapshot["project"]
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<corpus name="{_xml_text(project["name"])}" '
            f'schema="{SCHEMA}" version="{SCHEMA_VERSION}" '
            f'exported="{_xml_text(snapshot["exported_at"])}">'
        ),
    ]
    for segment in snapshot["segments"]:
        parts.append(
            f'<segment id="{segment["segment_id"]}" source="{segment["source_id"]}" '
            f'index="{segment["segment_index"]}" revision="{segment["definition_revision"]}" '
            f'start="{segment["start_seconds"]}" end="{segment["end_seconds"]}">'
        )
        parts.append(f"<transcript>{_xml_text(segment['transcript'])}</transcript>")
        parts.append("<annotations>")
        for row in segment["annotations"]:
            if row["removed_at"] is not None:
                continue
            parts.append(
                f'<annotation id="{row["annotation_id"]}" '
                f'annotator="{_xml_text(row["annotator"])}" '
                f'label="{_xml_text(row["label"])}"/>'
            )
        parts.append("</annotations></segment>")
    parts.append("</corpus>")
    return "\n".join(parts).encode("utf-8")


def _render_doccano(snapshot: dict) -> bytes:
    lines = []
    for segment in snapshot["segments"]:
        lines.append(
            json.dumps(
                {
                    "id": segment["segment_id"],
                    "text": segment["transcript"],
                    "label": _labels_for_training(snapshot, segment),
                    "split": segment.get("split"),
                },
                ensure_ascii=False,
            )
        )
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _render_label_studio(snapshot: dict) -> bytes:
    tasks = []
    for segment in snapshot["segments"]:
        labels = _labels_for_training(snapshot, segment)
        tasks.append(
            {
                "data": {
                    "text": segment["transcript"],
                    "segment_id": segment["segment_id"],
                    "split": segment.get("split"),
                    "start_seconds": segment["start_seconds"],
                    "end_seconds": segment["end_seconds"],
                },
                "predictions": [
                    {
                        "result": [
                            {
                                "from_name": "label",
                                "to_name": "text",
                                "type": "choices",
                                "value": {"choices": labels},
                            }
                        ]
                    }
                ]
                if labels
                else [],
            }
        )
    return _json_bytes(tasks)


def _render_hf(snapshot: dict) -> bytes:
    names = [row["name"] for row in snapshot["label_set"]]
    lines = [
        json.dumps(
            {"__meta__": True, "task": "segment_classification", "label_names": names, "supervision_policy": snapshot.get("supervision_policy"), "split": snapshot.get("split"), "dataset_version": snapshot.get("dataset_version")},
            ensure_ascii=False,
        )
    ]
    for segment in snapshot["segments"]:
        lines.append(
            json.dumps(
                {
                    "id": segment["segment_id"],
                    "text": segment["transcript"],
                    "labels": _labels_for_training(snapshot, segment),
                    "split": segment.get("split"),
                },
                ensure_ascii=False,
            )
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_spacy(snapshot: dict) -> bytes:
    label_names = [row["name"] for row in snapshot["label_set"]]
    docs = []
    for segment in snapshot["segments"]:
        active = set(_labels_for_training(snapshot, segment))
        docs.append(
            [
                segment["transcript"],
                {
                    "entities": [],
                    "cats": {name: 1.0 if name in active else 0.0 for name in label_names},
                },
            ]
        )
    return _json_bytes(docs)


def _render_llm(snapshot: dict) -> bytes:
    lines = []
    for segment in snapshot["segments"]:
        labels = _labels_for_training(snapshot, segment)
        lines.append(
            json.dumps(
                {
                    "messages": [
                        {
                            "role": "system",
                            "content": "Assign the segment labels that apply. Reply with a JSON list of label names.",
                        },
                        {"role": "user", "content": segment["transcript"]},
                        {"role": "assistant", "content": json.dumps(labels, ensure_ascii=False)},
                    ],
                    "metadata": {
                        "segment_id": segment["segment_id"],
                        "definition_revision": segment["definition_revision"],
                        "split": segment.get("split"),
                    },
                },
                ensure_ascii=False,
            )
        )
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _xlsx_sheet(rows: list[list]) -> str:
    body = []
    for index, row in enumerate(rows, start=1):
        cells = []
        for col, value in enumerate(row, start=1):
            letter = chr(ord("A") + col - 1)
            cells.append(
                f'<c r="{letter}{index}" t="inlineStr"><is><t>{_xml_text(value)}</t></is></c>'
            )
        body.append(f'<row r="{index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(body)}</sheetData></worksheet>"
    )


def _render_xlsx(snapshot: dict) -> bytes:
    segment_rows = [["segment_key", "segment_index", "split", "transcript", "labels", "revision", "segment_id"]]
    ann_rows = [["segment_key", "annotator", "label", "removed_at", "segment_id"]]
    asg_rows = [["segment_key", "assignee", "status", "segment_id"]]
    asr_rows = [["segment_key", "provider", "model", "revision", "aligned", "text", "segment_id"]]
    for segment in snapshot["segments"]:
        key = segment.get("segment_key") or ""
        segment_rows.append(
            [
                key,
                segment["segment_index"],
                segment.get("split") or "",
                segment["transcript"],
                "|".join(_labels_for_training(snapshot, segment)),
                segment["definition_revision"],
                segment["segment_id"],
            ]
        )
        for row in segment["annotations"]:
            ann_rows.append(
                [key, row["annotator"], row["label"], row["removed_at"] or "", segment["segment_id"]]
            )
        for row in segment["assignments"]:
            asg_rows.append([key, row["assignee"], row["status"], segment["segment_id"]])
        for row in segment["asr_runs"]:
            asr_rows.append(
                [
                    key,
                    row["provider"],
                    row["model"],
                    row["segment_revision"],
                    row["aligned"],
                    row["text"],
                    segment["segment_id"],
                ]
            )
    info_rows = [
        ["project", snapshot["project"]["name"]],
        ["exported_at", snapshot["exported_at"]],
        ["schema", snapshot["export_schema_version"]],
        ["dataset_version", snapshot.get("dataset_version") or ""],
        ["content_hash", snapshot.get("content_hash") or ""],
        ["supervision_policy", snapshot.get("supervision_policy") or ""],
        ["split", str(snapshot.get("split") or "")],
        ["segments", snapshot["counts"]["segments"]],
        ["annotations", snapshot["counts"]["annotations"]],
    ]
    sheets = {
        "Segments": segment_rows,
        "Annotations": ann_rows,
        "Assignments": asg_rows,
        "ASR": asr_rows,
        "Info": info_rows,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
"""
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        sheet_refs = []
        rels = []
        for index, name in enumerate(sheets, start=1):
            sheet_refs.append(f'<sheet name="{_xml_text(name)}" sheetId="{index}" r:id="rId{index}"/>')
            rels.append(
                f'<Relationship Id="rId{index}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{index}.xml"/>'
            )
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _xlsx_sheet(sheets[name]))
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{''.join(sheet_refs)}</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(rels)
            + "</Relationships>",
        )
    return buffer.getvalue()


def _render_dataset_zip(snapshot: dict) -> bytes:
    from apps.core.storage import get_storage

    storage = get_storage()
    buffer = io.BytesIO()
    sources_by_id = {row["source_id"]: row for row in snapshot["sources"]}
    settings = snapshot.get("settings") or {}

    metadata_rows = [
        [
            "segment_key",
            "segment_index",
            "split",
            "youtube_video_id",
            "youtube_url",
            "start_seconds",
            "end_seconds",
            "duration_seconds",
            "definition_revision",
            "transcript",
            "audio_file",
            "sample_rate_hz",
            "channels",
            "format",
            "audio_reviewed_at",
            "segment_id",
            "source_id",
        ]
    ]
    annotation_rows = [
        [
            "segment_key",
            "segment_index",
            "label",
            "annotator",
            "created_at",
            "removed_at",
            "segment_id",
            "annotation_id",
            "annotator_id",
        ]
    ]
    source_rows = [
        [
            "youtube_video_id",
            "youtube_url",
            "title",
            "channel_name",
            "duration_seconds",
            "source_status",
            "source_id",
        ]
    ]
    for row in snapshot["sources"]:
        source_rows.append(
            [
                row["youtube_video_id"],
                row["youtube_url"],
                row.get("title") or "",
                row.get("channel_name") or "",
                row.get("duration_seconds") or "",
                row.get("source_status") or "",
                row["source_id"],
            ]
        )

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for segment in snapshot["segments"]:
            source = sources_by_id.get(segment["source_id"], {})
            artifact = segment.get("current_artifact")
            audio_name = ""
            sample_rate = ""
            channels = ""
            fmt = ""
            yt = source.get("youtube_video_id") or segment.get("youtube_video_id") or "source"
            if artifact and artifact.get("verified") and artifact.get("artifact_id"):
                ext = (artifact.get("format") or "wav").lower()
                audio_name = f"segment_{yt}_{segment['segment_index']:06d}.{ext}"
                try:
                    art_row = ProcessingArtifact.objects.filter(
                        pk=artifact["artifact_id"]
                    ).first()
                    if art_row is None or not art_row.storage_key:
                        raise FileNotFoundError
                    data = storage.get(art_row.storage_key)
                    archive.writestr(f"audio/{audio_name}", data)
                except FileNotFoundError:
                    audio_name = ""
                sample_rate = artifact.get("sample_rate_hz") or ""
                channels = artifact.get("channels") or ""
                fmt = artifact.get("format") or ""

            metadata_rows.append(
                [
                    segment.get("segment_key") or "",
                    segment["segment_index"],
                    segment.get("split") or "",
                    source.get("youtube_video_id") or "",
                    source.get("youtube_url") or "",
                    segment["start_seconds"],
                    segment["end_seconds"],
                    segment["duration_seconds"],
                    segment["definition_revision"],
                    segment.get("transcript") or "",
                    f"audio/{audio_name}" if audio_name else "",
                    sample_rate,
                    channels,
                    fmt,
                    segment.get("audio_reviewed_at") or "",
                    segment["segment_id"],
                    segment["source_id"],
                ]
            )
            for ann in segment.get("annotations") or []:
                annotation_rows.append(
                    [
                        segment.get("segment_key") or "",
                        segment["segment_index"],
                        ann["label"],
                        ann.get("annotator") or "",
                        ann.get("created_at") or "",
                        ann.get("removed_at") or "",
                        segment["segment_id"],
                        ann["annotation_id"],
                        ann.get("annotator_id") or "",
                    ]
                )

        archive.writestr("metadata.csv", _csv_bytes(metadata_rows[0], metadata_rows[1:]))
        archive.writestr(
            "annotations.csv",
            _csv_bytes(annotation_rows[0], annotation_rows[1:]),
        )
        archive.writestr("sources.csv", _csv_bytes(source_rows[0], source_rows[1:]))

        label_lines = []
        for label in snapshot.get("label_set") or []:
            label_lines.append(f"- **{label['name']}**")
            if label.get("description"):
                label_lines.append(f"  - Definition: {label['description']}")
            if label.get("include_guidance"):
                label_lines.append(f"  - Include: {label['include_guidance']}")
            if label.get("exclude_guidance"):
                label_lines.append(f"  - Exclude: {label['exclude_guidance']}")

        readme = "\n".join(
            [
                f"# {snapshot['project']['name']}",
                "",
                f"- Language: {snapshot['project'].get('language') or '—'}",
                f"- Exported at: {snapshot['exported_at']}",
                f"- Schema: {snapshot['export_schema']} {snapshot['export_schema_version']}",
                f"- Ready-only filter: {snapshot.get('ready_only', False)}",
                f"- Sources: {snapshot['counts']['sources']}",
                f"- Segments: {snapshot['counts']['segments']}",
                f"- Annotations: {snapshot['counts']['annotations']}",
                f"- Project ID (opaque): `{snapshot['project']['project_id']}`",
                f"- Dataset version: `{snapshot.get('dataset_version') or '—'}`",
                f"- Content hash: `{snapshot.get('content_hash') or '—'}`",
                f"- Supervision policy: {snapshot.get('supervision_policy') or '—'}",
                f"- Split: {snapshot.get('split') or '—'}",
                "",
                "## Splits and supervision",
                "- Prefer `by_source` splits so the same YouTube video never appears in both train and test.",
                "- Do not randomly split by segment for speech tasks — that leaks acoustic content across folds.",
                "- Training views use `supervised_labels` (majority by default; `gold` uses OWNER adjudication when present).",
                "- Research JSON keeps full annotation episodes for IAA plus `gold_labels` when adjudicated.",
                "- `dataset_version` / `content_hash` identify this snapshot; `exported_at` is not part of the hash.",
                f"- License: {snapshot['project'].get('license') or '—'}",
                f"- Consent notes: {snapshot['project'].get('consent_notes') or '—'}",
                "",
                "## Segment keys",
                "- `segment_key` is `{youtube_video_id}#{segment_index}` — stable human handle alongside opaque `segment_id`.",
                "- Audio files use `segment_{youtube_video_id}_{index}.{ext}` when an artifact is present.",
                "",
                "## Audio configuration",
                f"- Format: {settings.get('output_format', '—')}",
                f"- Encoding: {settings.get('encoding', '—')}",
                f"- Sample rate: {settings.get('sample_rate_hz', '—')} Hz",
                f"- Channels: {settings.get('channels', '—')}",
                f"- Loudness normalization: {settings.get('loudness_normalization', '—')}",
                "",
                "## Readiness policy",
                f"- Require audio review: {settings.get('require_audio_review', '—')}",
                f"- Require transcript: {settings.get('require_transcript', '—')}",
                f"- Require annotation: {settings.get('require_annotation', '—')}",
                "",
                "## Label definitions",
                *(label_lines or ["- (none)"]),
                "",
                "## Contents",
                "- `audio/` — verified current artifacts when available",
                "- `metadata.csv` — segment provenance and audio paths",
                "- `annotations.csv` — human annotation episodes",
                "- `sources.csv` — YouTube source metadata",
                "",
            ]
        )
        archive.writestr("README.md", readme.encode("utf-8"))

    return buffer.getvalue()


_RENDERERS = {
    "json": _render_json,
    "jsonl": _render_jsonl,
    "json_segments": _render_json_segments,
    "xml": _render_xml,
    "csv_segments": _render_csv_segments,
    "csv_annotations": _render_csv_annotations,
    "csv_assignments": _render_csv_assignments,
    "xlsx": _render_xlsx,
    "doccano_jsonl": _render_doccano,
    "label_studio_json": _render_label_studio,
    "hf_jsonl": _render_hf,
    "spacy_json": _render_spacy,
    "json_llm": _render_llm,
    "dataset_zip": _render_dataset_zip,
}

