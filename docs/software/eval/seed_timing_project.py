"""Create a YouAudioLab project + sources + segments from sample_segments.csv.

Requires Django DB (docker compose up) and an owner user.

Usage:

  set DJANGO_SETTINGS_MODULE=config.settings.dev
  python docs/software/eval/seed_timing_project.py --email owner@example.com
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

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from apps.workspace.models import AppUser, VideoSource  # noqa: E402
from apps.workspace.services.project import ProjectService  # noqa: E402
from apps.workspace.services.segment import SegmentService  # noqa: E402
from apps.workspace.services.source import SourceService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=HERE / "sample_segments.csv")
    parser.add_argument("--email", required=True, help="Existing owner user email")
    parser.add_argument("--name", default="SoftwareX timing pilot N=60")
    parser.add_argument(
        "--mark-ready",
        action="store_true",
        help="Mark sources READY with a large duration so segments can be created without metadata fetch",
    )
    args = parser.parse_args()

    user = AppUser.objects.filter(email=args.email).first()
    if user is None:
        raise SystemExit(f"User not found: {args.email}")

    project = ProjectService().create(
        name=args.name,
        owner_user_id=user.id,
        description="SoftwareX timing pilot from audio_manifest.csv",
        language="vi",
    )

    sources = SourceService()
    segments = SegmentService()
    source_by_video: dict[str, VideoSource] = {}

    with args.sample.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    for row in rows:
        vid = row["video_id"]
        if vid not in source_by_video:
            try:
                source = sources.import_source(
                    project_id=project.id,
                    youtube_url=row["url"],
                    actor_user_id=user.id,
                )
            except Exception:
                source = VideoSource.objects.get(project_id=project.id, youtube_video_id=vid)
            if args.mark_ready:
                source.source_status = VideoSource.Status.READY
                source.duration_seconds = source.duration_seconds or 10_000.0
                source.title = source.title or row.get("film") or vid
                source.save()
            source_by_video[vid] = source

        source = source_by_video[vid]
        if source.source_status != VideoSource.Status.READY and not args.mark_ready:
            print(f"WARN source {vid} not READY; segment create may fail bounds check")
        seg = segments.create(
            source_id=source.id,
            start_seconds=float(row["start_sec"]),
            end_seconds=float(row["end_sec"]),
            actor_user_id=user.id,
            transcript=row["segment_id"],
        )
        print(f"created {row['segment_id']} -> segment {seg.id}")

    mapping_path = HERE / "yal_segment_map.csv"
    with mapping_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["segment_id", "yal_segment_id", "video_id", "project_id"],
        )
        writer.writeheader()
        for row in rows:
            vid = row["video_id"]
            source = source_by_video[vid]
            match = (
                source.segments.filter(
                    start_seconds=float(row["start_sec"]),
                    end_seconds=float(row["end_sec"]),
                    deleted_at__isnull=True,
                )
                .order_by("segment_index")
                .first()
            )
            writer.writerow(
                {
                    "segment_id": row["segment_id"],
                    "yal_segment_id": str(match.id) if match else "",
                    "video_id": vid,
                    "project_id": str(project.id),
                }
            )

    print(f"project_id={project.id}")
    print(f"Wrote {mapping_path}")


if __name__ == "__main__":
    main()
