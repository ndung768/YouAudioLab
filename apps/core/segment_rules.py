"""Segment bound validation and revision decision helpers (pure)."""

from __future__ import annotations

from apps.core.errors import ValidationError


def validate_segment_bounds(
    start_seconds: float,
    end_seconds: float,
    *,
    source_duration_seconds: float | None = None,
) -> float:
    """Validate start/end; return derived duration. No silent clamp."""
    fields: list[dict[str, str]] = []

    if start_seconds < 0:
        fields.append(
            {
                "field": "start_seconds",
                "code": "START_NEGATIVE",
                "message": "start_seconds must be >= 0",
            }
        )
    if end_seconds <= start_seconds:
        fields.append(
            {
                "field": "end_seconds",
                "code": "END_LE_START",
                "message": "end_seconds must be > start_seconds",
            }
        )

    if source_duration_seconds is not None:
        if start_seconds >= source_duration_seconds:
            fields.append(
                {
                    "field": "start_seconds",
                    "code": "START_GE_DURATION",
                    "message": "start_seconds must be < source duration",
                }
            )
        if end_seconds > source_duration_seconds:
            fields.append(
                {
                    "field": "end_seconds",
                    "code": "END_GT_DURATION",
                    "message": "end_seconds must be <= source duration",
                }
            )

    if fields:
        raise ValidationError(
            "Segment bounds validation failed",
            details={"fields": fields},
        )

    return float(end_seconds - start_seconds)


def bounds_changed(
    *,
    old_start: float,
    old_end: float,
    new_start: float,
    new_end: float,
) -> bool:
    return old_start != new_start or old_end != new_end
