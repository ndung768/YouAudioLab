"""Select a fixed pilot sample from audio_manifest.csv."""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

DEFAULT_MANIFEST = Path(r"d:\researcher\audio_manifest.csv")
HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "sample_segments.csv"

FIELDNAMES = [
    "segment_id",
    "film",
    "region",
    "url",
    "video_id",
    "start_sec",
    "end_sec",
    "duration_s",
    "audio_path",
]


def load_pool(
    manifest: Path,
    *,
    min_s: float,
    max_s: float,
) -> list[dict[str, str | float]]:
    with manifest.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    pool: list[dict[str, str | float]] = []
    for row in rows:
        if (row.get("status") or "").strip() != "ok":
            continue
        try:
            start = float(row["start_sec"])
            end = float(row["end_sec"])
        except (KeyError, TypeError, ValueError):
            continue
        duration = end - start
        if duration < min_s or duration > max_s:
            continue
        pool.append(
            {
                "segment_id": row["id"].strip(),
                "film": (row.get("film") or "").strip(),
                "region": (row.get("region") or "").strip(),
                "url": (row.get("url") or "").strip(),
                "video_id": (row.get("video_id") or "").strip(),
                "start_sec": start,
                "end_sec": end,
                "duration_s": round(duration, 3),
                "audio_path": (row.get("audio_path") or "").strip(),
            }
        )
    return pool


def select_sample(
    pool: list[dict[str, str | float]],
    *,
    n: int,
    seed: int,
) -> list[dict[str, str | float]]:
    if len(pool) < n:
        raise SystemExit(f"Pool has {len(pool)} rows; need at least {n}.")
    rng = random.Random(seed)
    chosen = rng.sample(pool, n)
    return sorted(chosen, key=lambda r: str(r["segment_id"]))


def write_sample(path: Path, rows: list[dict[str, str | float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "segment_id": row["segment_id"],
                    "film": row["film"],
                    "region": row["region"],
                    "url": row["url"],
                    "video_id": row["video_id"],
                    "start_sec": f"{float(row['start_sec']):.3f}",
                    "end_sec": f"{float(row['end_sec']):.3f}",
                    "duration_s": f"{float(row['duration_s']):.3f}",
                    "audio_path": row["audio_path"],
                }
            )


def write_timing_templates(sample: list[dict[str, str | float]], out_dir: Path) -> None:
    """Pre-fill segment_id rows; leave timestamps empty for the experimenter."""
    manual_path = out_dir / "timing_manual.csv"
    tool_path = out_dir / "timing_tool_human.csv"
    machine_path = out_dir / "machine_jobs.csv"

    human_fields = ["segment_id", "started_at", "ended_at", "duration_s", "notes"]
    for path in (manual_path, tool_path):
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=human_fields)
            writer.writeheader()
            for row in sample:
                writer.writerow(
                    {
                        "segment_id": row["segment_id"],
                        "started_at": "",
                        "ended_at": "",
                        "duration_s": "",
                        "notes": "",
                    }
                )

    machine_fields = [
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
    with machine_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=machine_fields)
        writer.writeheader()
        for row in sample:
            for job_type in ("extract", "asr"):
                writer.writerow(
                    {
                        "job_id": "",
                        "segment_id": row["segment_id"],
                        "job_type": job_type,
                        "queued_at": "",
                        "started_at": "",
                        "finished_at": "",
                        "duration_s": "",
                        "status": "",
                        "notes": "",
                    }
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Path to audio_manifest.csv (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-s", type=float, default=8.0)
    parser.add_argument("--max-s", type=float, default=45.0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--write-templates",
        action="store_true",
        default=True,
        help="Also rewrite empty timing CSV templates for the sample (default: on)",
    )
    parser.add_argument(
        "--no-write-templates",
        action="store_false",
        dest="write_templates",
    )
    args = parser.parse_args()

    if not args.manifest.is_file():
        raise SystemExit(f"Manifest not found: {args.manifest}")

    pool = load_pool(args.manifest, min_s=args.min_s, max_s=args.max_s)
    sample = select_sample(pool, n=args.n, seed=args.seed)
    write_sample(args.out, sample)

    total_s = sum(float(r["duration_s"]) for r in sample)
    n_videos = len({r["video_id"] for r in sample})
    print(f"Wrote {args.out}")
    print(f"pool={len(pool)} n={len(sample)} seed={args.seed}")
    print(
        f"audio_min={total_s / 60:.2f} mean_s={total_s / len(sample):.1f} "
        f"videos={n_videos}"
    )
    print("ids=" + ",".join(str(r["segment_id"]) for r in sample))

    if args.write_templates:
        write_timing_templates(sample, args.out.parent)
        print(f"Wrote timing templates under {args.out.parent}")


if __name__ == "__main__":
    main()
