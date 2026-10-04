"""Export ProcessingJob timestamps for a project into machine_jobs.csv.

Requires Django settings and a running database. Optional when using
run_machine_local.py instead.

Usage (from repo root, venv active):

  set DJANGO_SETTINGS_MODULE=config.settings.local
  python docs/software/eval/export_machine_jobs_from_db.py --project-id <uuid>
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django  # noqa: E402

django.setup()

from apps.processing.models import ProcessingJob  # noqa: E402
from apps.workspace.models import AudioSegment  # noqa: E402


def fmt(dt) -> str:
    if dt is None:
        return ""
    return dt.isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--sample", type=Path, default=HERE / "sample_segments.csv")
    parser.add_argument("--out", type=Path, default=HERE / "machine_jobs.csv")
    parser.add_argument(
        "--external-id-field",
        default="notes",
        help="Unused placeholder; matching uses start/end + youtube id via sample CSV",
    )
    args = parser.parse_args()

    sample_ids: dict[tuple[str, float, float], str] = {}
    with args.sample.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            key = (
                row["video_id"],
                round(float(row["start_sec"]), 3),
                round(float(row["end_sec"]), 3),
            )
            sample_ids[key] = row["segment_id"]

    jobs = (
        ProcessingJob.objects.filter(project_id=args.project_id)
        .select_related("segment", "segment__source")
        .order_by("queued_at", "created_at")
    )

    out_rows = []
    for job in jobs:
        segment: AudioSegment | None = job.segment
        if segment is None or segment.source is None:
            continue
        key = (
            segment.source.youtube_video_id,
            round(float(segment.start_seconds), 3),
            round(float(segment.end_seconds), 3),
        )
        external = sample_ids.get(key, "")
        duration_s = ""
        if job.started_at and job.finished_at:
            duration_s = f"{(job.finished_at - job.started_at).total_seconds():.3f}"
        out_rows.append(
            {
                "job_id": str(job.id),
                "segment_id": external or str(segment.id),
                "job_type": (
                    "extract"
                    if job.job_type == ProcessingJob.JobType.EXTRACT_SEGMENT_AUDIO
                    else "asr"
                    if job.job_type == ProcessingJob.JobType.TRANSCRIBE_SEGMENT_AUDIO
                    else (job.job_type or "").lower()
                ),
                "queued_at": fmt(job.queued_at),
                "started_at": fmt(job.started_at),
                "finished_at": fmt(job.finished_at),
                "duration_s": duration_s,
                "status": job.status or "",
                "notes": f"db export; youtube={segment.source.youtube_video_id}",
            }
        )

    fields = [
        "job_id",
        "segment_id",
        "job_type",
        "queued_at",
        "started_at",
        "finished_at",
        "duration_s",
        "status",
        "notes",
    ]
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"Wrote {len(out_rows)} jobs to {args.out}")


if __name__ == "__main__":
    main()
