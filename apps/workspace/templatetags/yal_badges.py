from __future__ import annotations

from django import template
from django.utils.translation import gettext as _

register = template.Library()

_SOURCE_STATUS = {
    "PENDING_METADATA": ("Metadata pending", "warning"),
    "READY": ("Ready", "success"),
    "METADATA_FAILED": ("Metadata failed", "danger"),
}

_PROJECT_STATUS = {
    "ACTIVE": ("Active", "success"),
    "ARCHIVED": ("Archived", "secondary"),
}

_PROCESSING_STATUS = {
    "PENDING": ("Pending", "secondary"),
    "PROCESSING": ("Processing", "warning"),
    "COMPLETED": ("Completed", "success"),
    "FAILED": ("Failed", "danger"),
}

_LABEL_STATUS = {
    "ACTIVE": ("Active", "success"),
    "INACTIVE": ("Inactive", "secondary"),
}

_JOB_STATUS = {
    "QUEUED": ("Queued", "secondary"),
    "RUNNING": ("Running", "warning"),
    "SUCCEEDED": ("Succeeded", "success"),
    "FAILED": ("Failed", "danger"),
    "STALE": ("Out of date", "secondary"),
    "CANCELLED": ("Cancelled", "secondary"),
}

_GATE_LABELS = {
    "SOURCE_VALID": "Source",
    "SEGMENT_VALID": "Bounds",
    "AUDIO_VALID": "Audio",
    "AUDIO_REVIEWED": "Review",
    "TRANSCRIPT_VALID": "Transcript",
    "ANNOTATION_VALID": "Label",
    "NOT_DELETED": "Deleted",
}


def _badge(mapping: dict, value: str) -> dict:
    key = str(value)
    if key in mapping:
        label, tone = mapping[key]
        return {"label": _(label), "tone": tone, "raw": value}
    return {"label": key, "tone": "secondary", "raw": value}


@register.filter
def readiness_gate_label(code: str) -> str:
    key = str(code or "")
    if key in _GATE_LABELS:
        return _(_GATE_LABELS[key])
    return key


@register.inclusion_tag("partials/status_badge.html")
def status_badge(value: str, kind: str = "source"):
    if kind == "source":
        mapping = _SOURCE_STATUS
    elif kind == "processing":
        mapping = _PROCESSING_STATUS
    elif kind == "label":
        mapping = _LABEL_STATUS
    elif kind == "job":
        mapping = _JOB_STATUS
    else:
        mapping = _PROJECT_STATUS
    return _badge(mapping, value)


@register.inclusion_tag("partials/status_badge.html")
def job_status_badge(job):
    if job.cancel_requested_at and job.status in {"QUEUED", "RUNNING"}:
        return {"label": _("Cancellation requested…"), "tone": "warning", "raw": "CANCEL_REQUESTED"}
    return _badge(_JOB_STATUS, job.status)


@register.inclusion_tag("partials/readiness_status.html")
def readiness_status(is_ready: bool, failed_gates=()):
    chips = []
    for code in failed_gates or ():
        chips.append(
            {
                "code": code,
                "label": readiness_gate_label(code),
            }
        )
    return {
        "is_ready": bool(is_ready),
        "gate_chips": chips,
    }
