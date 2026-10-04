"""Interactive stopwatch for Manual or Tool-human timing rows.

Opens each sample segment in order; press Enter to start, Enter to stop.
Writes duration_s into the chosen timing CSV.

Usage:

  python docs/software/eval/time_human_session.py --mode manual
  python docs/software/eval/time_human_session.py --mode tool
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    return fields, rows


def save_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def maybe_open_audio(path: Path) -> None:
    if not path.is_file():
        print(f"  (audio missing: {path})")
        return
    try:
        if sys.platform.startswith("win"):
            os_start = getattr(__import__("os"), "startfile", None)
            if os_start:
                os_start(path)  # type: ignore[misc]
                return
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603
    except OSError as exc:
        print(f"  (could not open audio: {exc})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("manual", "tool"), required=True)
    parser.add_argument("--sample", type=Path, default=HERE / "sample_segments.csv")
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Override timing CSV path",
    )
    parser.add_argument(
        "--open-audio",
        action="store_true",
        help="Try to open each MP3 in the default player before timing",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip rows that already have duration_s",
    )
    args = parser.parse_args()

    target = args.csv or (
        HERE / "timing_manual.csv" if args.mode == "manual" else HERE / "timing_tool_human.csv"
    )
    sample_by_id = {}
    with args.sample.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            sample_by_id[row["segment_id"]] = row

    fields, rows = load_csv(target)
    if "duration_s" not in fields:
        raise SystemExit(f"{target} missing duration_s column")

    print(f"Timing file: {target}")
    print("For each segment: prepare to work, press Enter to START, Enter to STOP.")
    print("Type s + Enter to skip, q + Enter to quit.\n")

    for row in rows:
        seg_id = row.get("segment_id") or ""
        if not seg_id:
            continue
        if args.resume and (row.get("duration_s") or "").strip():
            print(f"{seg_id}: already filled ({row['duration_s']}s), skip")
            continue

        sample = sample_by_id.get(seg_id, {})
        audio = Path(sample.get("audio_path") or "")
        print(f"=== {seg_id} ({sample.get('duration_s', '?')}s audio) ===")
        if args.open_audio:
            maybe_open_audio(audio)
        else:
            print(f"  audio: {audio}")

        cmd = input("Enter=start, s=skip, q=quit > ").strip().lower()
        if cmd == "q":
            break
        if cmd == "s":
            continue

        t0 = time.time()
        print("  ... timing ...")
        input("Enter=stop > ")
        t1 = time.time()
        dur = t1 - t0
        row["started_at"] = fmt(t0)
        row["ended_at"] = fmt(t1)
        row["duration_s"] = f"{dur:.3f}"
        save_csv(target, fields, rows)
        print(f"  saved {dur:.1f}s\n")

    print(f"Done. Re-run summarize_timing.py when both human CSVs and machine_jobs.csv are complete.")


if __name__ == "__main__":
    main()
