"""Inter-annotator agreement and label-balance metrics for Progress (OWNER)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from itertools import combinations

from apps.workspace.models import ProjectLabel, SegmentAnnotation, SegmentGoldLabel


@dataclass(frozen=True)
class AnnotatorPairAgreement:
    annotator_a_id: uuid.UUID
    annotator_a_name: str
    annotator_b_id: uuid.UUID
    annotator_b_name: str
    shared_segments: int
    mean_jaccard: float
    exact_match_rate: float
    mean_cohen_kappa: float | None


@dataclass(frozen=True)
class LabelBalanceRow:
    project_label_id: uuid.UUID
    name: str
    episode_count: int
    segment_count: int
    pct_of_episodes: float


@dataclass(frozen=True)
class AgreementReport:
    overlap_segment_count: int
    annotator_count: int
    pair_count: int
    gold_segment_count: int
    mean_jaccard: float | None
    exact_match_rate: float | None
    mean_cohen_kappa: float | None
    fleiss_kappa: float | None
    pairs: list[AnnotatorPairAgreement] = field(default_factory=list)
    label_balance: list[LabelBalanceRow] = field(default_factory=list)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _cohen_binary(a_pos: set, b_pos: set, items: list) -> float | None:
    n = len(items)
    if n == 0:
        return None
    both = only_a = only_b = neither = 0
    for item in items:
        in_a = item in a_pos
        in_b = item in b_pos
        if in_a and in_b:
            both += 1
        elif in_a:
            only_a += 1
        elif in_b:
            only_b += 1
        else:
            neither += 1
    po = (both + neither) / n
    pa = (both + only_a) / n
    pb = (both + only_b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if abs(1 - pe) < 1e-12:
        return 1.0 if abs(po - 1) < 1e-12 else 0.0
    return (po - pe) / (1 - pe)


def _mean_cohen_for_pair(
    a_labels: dict,
    b_labels: dict,
    shared_ids: list,
    catalog: list[str],
) -> float | None:
    """Mean Cohen's κ across catalog labels (present/absent) on shared segments."""
    kappas: list[float] = []
    for name in catalog:
        a_pos = {sid for sid in shared_ids if name in a_labels.get(sid, set())}
        b_pos = {sid for sid in shared_ids if name in b_labels.get(sid, set())}
        if not a_pos and not b_pos:
            continue
        kappa = _cohen_binary(a_pos, b_pos, shared_ids)
        if kappa is not None:
            kappas.append(kappa)
    if not kappas:
        return None
    return sum(kappas) / len(kappas)


def _fleiss_binary(items: list[tuple[int, int]]) -> float | None:
    """Generalized Fleiss' κ for binary ratings with variable rater counts.

    Each item is (n_raters, n_positive) with n_raters >= 2.
    """
    usable = [(n, pos) for n, pos in items if n >= 2]
    if not usable:
        return None
    sum_nn1 = 0
    sum_agree = 0
    sum_n = 0
    sum_pos = 0
    for n, pos in usable:
        neg = n - pos
        sum_n += n
        sum_pos += pos
        sum_nn1 += n * (n - 1)
        sum_agree += pos * (pos - 1) + neg * (neg - 1)
    if sum_nn1 == 0 or sum_n == 0:
        return None
    p_bar = sum_agree / sum_nn1
    p1 = sum_pos / sum_n
    p_e = p1 * p1 + (1 - p1) * (1 - p1)
    if abs(1 - p_e) < 1e-12:
        return 1.0 if abs(p_bar - 1) < 1e-12 else 0.0
    return (p_bar - p_e) / (1 - p_e)


class AgreementService:
    """Compute multi-label set agreement from active annotation episodes."""

    MAX_PAIRS = 10

    def report(self, project_id: uuid.UUID) -> AgreementReport:
        catalog = [
            pl.display_name
            for pl in ProjectLabel.objects.filter(
                project_id=project_id, scope__in=ProjectLabel.SEGMENT_SCOPES
            )
            .select_related("label")
            .order_by("sort_order", "id")
        ]
        rows = list(
            SegmentAnnotation.objects.filter(
                segment__source__project_id=project_id,
                segment__deleted_at__isnull=True,
                removed_at__isnull=True,
            )
            .select_related("label__label", "annotator")
            .order_by("created_at")
        )

        by_segment: dict[uuid.UUID, dict[uuid.UUID, set[str]]] = {}
        display_names: dict[uuid.UUID, str] = {}
        for row in rows:
            aid = row.annotator_id
            display_names[aid] = row.annotator.display_name
            labels = by_segment.setdefault(row.segment_id, {}).setdefault(aid, set())
            labels.add(row.label.display_name)

        annotator_ids = sorted(display_names.keys(), key=lambda x: str(x))
        overlap = {
            sid: annotators
            for sid, annotators in by_segment.items()
            if len(annotators) >= 2
        }

        jaccards: list[float] = []
        exacts: list[float] = []
        pair_jaccard: dict[tuple[uuid.UUID, uuid.UUID], list[tuple[float, bool]]] = {}
        pair_segments: dict[tuple[uuid.UUID, uuid.UUID], list[uuid.UUID]] = {}

        for sid, annotators in overlap.items():
            ids = sorted(annotators.keys(), key=lambda x: str(x))
            for a_id, b_id in combinations(ids, 2):
                j = _jaccard(annotators[a_id], annotators[b_id])
                exact = annotators[a_id] == annotators[b_id]
                jaccards.append(j)
                exacts.append(1.0 if exact else 0.0)
                key = (a_id, b_id)
                pair_jaccard.setdefault(key, []).append((j, exact))
                pair_segments.setdefault(key, []).append(sid)

        mean_jaccard = (sum(jaccards) / len(jaccards)) if jaccards else None
        exact_match_rate = (sum(exacts) / len(exacts)) if exacts else None

        # Per-annotator labels by segment (for Cohen)
        by_ann_seg: dict[uuid.UUID, dict[uuid.UUID, set[str]]] = {}
        for sid, annotators in by_segment.items():
            for aid, names in annotators.items():
                by_ann_seg.setdefault(aid, {})[sid] = names

        pair_cohens: list[float] = []
        pair_rows: list[AnnotatorPairAgreement] = []
        for (a_id, b_id), samples in pair_jaccard.items():
            n = len(samples)
            shared = pair_segments.get((a_id, b_id), [])
            cohen = _mean_cohen_for_pair(
                by_ann_seg.get(a_id, {}),
                by_ann_seg.get(b_id, {}),
                shared,
                catalog,
            )
            if cohen is not None:
                pair_cohens.append(cohen)
            pair_rows.append(
                AnnotatorPairAgreement(
                    annotator_a_id=a_id,
                    annotator_a_name=display_names.get(a_id, str(a_id)),
                    annotator_b_id=b_id,
                    annotator_b_name=display_names.get(b_id, str(b_id)),
                    shared_segments=n,
                    mean_jaccard=sum(s[0] for s in samples) / n,
                    exact_match_rate=sum(1.0 if s[1] else 0.0 for s in samples) / n,
                    mean_cohen_kappa=cohen,
                )
            )
        pair_rows.sort(key=lambda r: (-r.shared_segments, -r.mean_jaccard))
        pair_rows = pair_rows[: self.MAX_PAIRS]

        fleiss_items: list[tuple[int, int]] = []
        names_for_fleiss = catalog or sorted(
            {name for annotators in overlap.values() for names in annotators.values() for name in names}
        )
        for annotators in overlap.values():
            n = len(annotators)
            for name in names_for_fleiss:
                pos = sum(1 for names in annotators.values() if name in names)
                fleiss_items.append((n, pos))

        gold_segment_count = (
            SegmentGoldLabel.objects.filter(
                segment__source__project_id=project_id,
                segment__deleted_at__isnull=True,
            )
            .values("segment_id")
            .distinct()
            .count()
        )

        return AgreementReport(
            overlap_segment_count=len(overlap),
            annotator_count=len(annotator_ids),
            pair_count=len(pair_jaccard),
            gold_segment_count=gold_segment_count,
            mean_jaccard=mean_jaccard,
            exact_match_rate=exact_match_rate,
            mean_cohen_kappa=(sum(pair_cohens) / len(pair_cohens)) if pair_cohens else None,
            fleiss_kappa=_fleiss_binary(fleiss_items),
            pairs=pair_rows,
            label_balance=self.label_balance(project_id),
        )

    def label_balance(self, project_id: uuid.UUID) -> list[LabelBalanceRow]:
        labels = list(
            ProjectLabel.objects.filter(
                project_id=project_id, scope__in=ProjectLabel.SEGMENT_SCOPES
            )
            .select_related("label")
            .order_by("sort_order", "created_at")
        )
        episodes = list(
            SegmentAnnotation.objects.filter(
                segment__source__project_id=project_id,
                segment__deleted_at__isnull=True,
                removed_at__isnull=True,
            ).values_list("label_id", "segment_id")
        )
        total_episodes = len(episodes) or 1
        by_label: dict[uuid.UUID, list[uuid.UUID]] = {}
        for label_id, segment_id in episodes:
            by_label.setdefault(label_id, []).append(segment_id)

        rows: list[LabelBalanceRow] = []
        for pl in labels:
            segs = by_label.get(pl.id, [])
            episode_count = len(segs)
            segment_count = len(set(segs))
            rows.append(
                LabelBalanceRow(
                    project_label_id=pl.id,
                    name=pl.display_name,
                    episode_count=episode_count,
                    segment_count=segment_count,
                    pct_of_episodes=round(100 * episode_count / total_episodes, 1),
                )
            )
        rows.sort(key=lambda r: (-r.episode_count, r.name.lower()))
        return rows
