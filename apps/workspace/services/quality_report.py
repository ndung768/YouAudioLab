"""OWNER quality report: duration histogram, per-video coverage, IAA strip."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from apps.workspace.models import (
    AudioSegment,
    Project,
    SegmentAnnotation,
    SegmentGoldLabel,
    VideoSource,
)
from apps.workspace.services.agreement import AgreementService
from apps.workspace.services.export_dataset import _assign_splits
from apps.workspace.services.membership import MembershipService
from apps.workspace.services.readiness import ReadinessService


DURATION_BUCKETS: tuple[tuple[str, str, float, float | None], ...] = (
    ("lt_3", "<3s", 0.0, 3.0),
    ("3_10", "3–10s", 3.0, 10.0),
    ("10_30", "10–30s", 10.0, 30.0),
    ("gte_30", "≥30s", 30.0, None),
)

COVERAGE_TABLE_LIMIT = 50


def _hours(seconds: float) -> float:
    return round(float(seconds) / 3600.0, 6)


def _bucket_key(duration: float) -> str:
    for key, _label, low, high in DURATION_BUCKETS:
        if high is None:
            if duration >= low:
                return key
        elif low <= duration < high:
            return key
    return "gte_30"


def _empty_bucket_counts() -> dict[str, dict[str, float | int]]:
    return {
        key: {"key": key, "label": label, "segment_count": 0, "hours": 0.0, "pct_of_hours": 0.0}
        for key, label, _low, _high in DURATION_BUCKETS
    }


def _finalize_buckets(raw: dict[str, dict], total_hours: float) -> list[dict]:
    denom = total_hours if total_hours > 0 else 1.0
    rows = []
    for key, _label, _low, _high in DURATION_BUCKETS:
        row = raw[key]
        hours = float(row["hours"])
        row["hours"] = round(hours, 6)
        row["pct_of_hours"] = round(100.0 * hours / denom, 1)
        rows.append(row)
    return rows


def _content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class QualityReport:
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.payload


class QualityReportService:
    def __init__(self) -> None:
        self.memberships = MembershipService()

    def build(
        self,
        project_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> QualityReport:
        self.memberships.require_owner(project_id, actor_user_id)
        project = Project.objects.select_related("settings").get(pk=project_id)

        sources = list(
            VideoSource.objects.filter(project_id=project_id).order_by("created_at")
        )
        segments = list(
            AudioSegment.objects.filter(
                source__project_id=project_id,
                deleted_at__isnull=True,
            )
            .select_related("source", "current_artifact", "current_artifact__job")
            .order_by("source__created_at", "segment_index")
        )

        split_input = [
            {"source_id": str(seg.source_id), "segment_id": str(seg.id)}
            for seg in segments
        ]
        split_meta, split_warnings = _assign_splits(
            split_input,
            strategy="by_source",
            seed=42,
            train=0.8,
            val=0.1,
            test=0.1,
        )
        split_by_segment = {row["segment_id"]: row.get("split") for row in split_input}
        split_by_source = {
            str(seg.source_id): split_by_segment.get(str(seg.id))
            for seg in segments
        }

        readiness_map = ReadinessService().evaluate_many(segments, project_id=project_id)

        annotated_ids: set[uuid.UUID] = set()
        annotators_by_segment: dict[uuid.UUID, set[uuid.UUID]] = {}
        gold_ids: set[uuid.UUID] = set()
        segment_ids = [s.id for s in segments]
        if segment_ids:
            for sid, aid in SegmentAnnotation.objects.filter(
                segment_id__in=segment_ids,
                removed_at__isnull=True,
            ).values_list("segment_id", "annotator_id"):
                annotated_ids.add(sid)
                annotators_by_segment.setdefault(sid, set()).add(aid)
            gold_ids = set(
                SegmentGoldLabel.objects.filter(
                    segment_id__in=segment_ids,
                ).values_list("segment_id", flat=True)
            )
        overlap_ids = {
            sid for sid, aids in annotators_by_segment.items() if len(aids) >= 2
        }

        total_seconds = sum(float(seg.duration_seconds or 0) for seg in segments)
        ready_ids = {seg.id for seg in segments if readiness_map[seg.id].is_ready}

        overall_raw = _empty_bucket_counts()
        by_split_raw: dict[str, dict] = {
            name: _empty_bucket_counts() for name in ("train", "val", "test")
        }
        for seg in segments:
            dur = float(seg.duration_seconds or 0)
            hours = _hours(dur)
            key = _bucket_key(dur)
            overall_raw[key]["segment_count"] += 1
            overall_raw[key]["hours"] += hours
            split = split_by_segment.get(str(seg.id))
            if split in by_split_raw:
                by_split_raw[split][key]["segment_count"] += 1
                by_split_raw[split][key]["hours"] += hours

        total_hours = _hours(total_seconds)
        duration_overall = _finalize_buckets(overall_raw, total_hours)
        duration_by_split = {
            name: _finalize_buckets(raw, sum(float(r["hours"]) for r in raw.values()))
            for name, raw in by_split_raw.items()
        }

        coverage: list[dict] = []
        segs_by_source: dict[uuid.UUID, list[AudioSegment]] = {}
        for seg in segments:
            segs_by_source.setdefault(seg.source_id, []).append(seg)

        for source in sources:
            rows = segs_by_source.get(source.id, [])
            hours = _hours(sum(float(s.duration_seconds or 0) for s in rows))
            coverage.append(
                {
                    "source_id": str(source.id),
                    "title": source.title or source.youtube_url,
                    "youtube_video_id": source.youtube_video_id,
                    "segment_count": len(rows),
                    "hours": hours,
                    "annotated": sum(1 for s in rows if s.id in annotated_ids),
                    "gold": sum(1 for s in rows if s.id in gold_ids),
                    "overlap": sum(1 for s in rows if s.id in overlap_ids),
                    "ready": sum(1 for s in rows if s.id in ready_ids),
                    "split": split_by_source.get(str(source.id)),
                }
            )

        iaa = AgreementService().report(project_id)
        iaa_strip = {
            "overlap_segment_count": iaa.overlap_segment_count,
            "annotator_count": iaa.annotator_count,
            "mean_jaccard": iaa.mean_jaccard,
            "exact_match_rate": iaa.exact_match_rate,
            "mean_cohen_kappa": iaa.mean_cohen_kappa,
            "fleiss_kappa": iaa.fleiss_kappa,
            "gold_segment_count": iaa.gold_segment_count,
        }

        generated_at = datetime.now(timezone.utc).isoformat()
        body = {
            "project": {
                "project_id": str(project.id),
                "name": project.name,
                "language": project.language,
                "license": project.license,
                "consent_notes": project.consent_notes,
            },
            "split": split_meta,
            "split_warnings": split_warnings,
            "counts": {
                "sources": len(sources),
                "segments": len(segments),
                "dataset_hours": total_hours,
                "ready": len(ready_ids),
                "gold": len(gold_ids),
                "overlap": len(overlap_ids),
                "annotated": len(annotated_ids),
            },
            "duration": {
                "overall": duration_overall,
                "by_split": duration_by_split,
            },
            "coverage": coverage,
            "iaa": iaa_strip,
        }
        digest = _content_hash(body)
        payload = {
            **body,
            "generated_at": generated_at,
            "content_hash": digest,
            "report_version": f"yal-qc2-{digest[:12]}",
        }
        return QualityReport(payload=payload)


def quality_report_hash(payload: dict) -> str:
    """Hash excluding generated_at / content_hash / report_version."""
    body = {
        k: v
        for k, v in payload.items()
        if k not in {"generated_at", "content_hash", "report_version"}
    }
    return _content_hash(body)
