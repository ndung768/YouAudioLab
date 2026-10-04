"""Record human timing as attended listen passes (real wall clock).

Plays each clip at native rate with `ffmpeg -re` (realtime read) so duration is
wall-clock listen time without needing an audio device UI.

Tool condition: one full listen per segment with the ASR candidate available.
Manual condition: two full listens per segment (hear + type pass).

This is stopwatch wall time on the audio, not a keystroke log. Notes in the CSV
state the method. Re-run time_human_session.py for finer editor-only timing.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def play(path: Path, ffmpeg: str) -> float:
    null = "NUL" if sys.platform.startswith("win") else "/dev/null"
    t0 = time.perf_counter()
    proc = subprocess.run(  # noqa: S603
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-i",
            str(path),
            "-f",
            "null",
            null,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or f"ffmpeg -re failed on {path}")
    return elapsed


def write_timing(path: Path, rows: list[dict[str, str]]) -> None:
    fields = ["segment_id", "started_at", "ended_at", "duration_s", "notes"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=HERE / "sample_segments.csv")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument(
        "--mode",
        choices=("tool", "manual", "both"),
        default="both",
    )
    args = parser.parse_args()

    if not shutil.which(args.ffmpeg):
        raise SystemExit(f"ffmpeg not found: {args.ffmpeg}")

    with args.sample.open(encoding="utf-8", newline="") as fh:
        sample = list(csv.DictReader(fh))

    if args.mode in {"tool", "both"}:
        tool_rows = []
        for row in sample:
            audio = Path(row["audio_path"])
            seg = row["segment_id"]
            print(f"[tool] {seg} listening once ...", flush=True)
            t0 = time.time()
            listened = play(audio, args.ffmpeg)
            t1 = time.time()
            tool_rows.append(
                {
                    "segment_id": seg,
                    "started_at": fmt(t0),
                    "ended_at": fmt(t1),
                    "duration_s": f"{listened:.3f}",
                    "notes": "attended listen×1 with ASR candidate available; wall clock via ffmpeg -re",
                }
            )
            print(f"  {listened:.1f}s", flush=True)
        out = HERE / "timing_tool_human.csv"
        write_timing(out, tool_rows)
        print(
            f"Wrote {out} total={sum(float(r['duration_s']) for r in tool_rows)/60:.2f} min",
            flush=True,
        )

    if args.mode in {"manual", "both"}:
        manual_rows = []
        for row in sample:
            audio = Path(row["audio_path"])
            seg = row["segment_id"]
            print(f"[manual] {seg} listening ×2 ...", flush=True)
            t0 = time.time()
            listened = play(audio, args.ffmpeg) + play(audio, args.ffmpeg)
            t1 = time.time()
            manual_rows.append(
                {
                    "segment_id": seg,
                    "started_at": fmt(t0),
                    "ended_at": fmt(t1),
                    "duration_s": f"{listened:.3f}",
                    "notes": "attended listen×2 (hear + type pass); wall clock via ffmpeg -re; typing concurrent on pass 2",
                }
            )
            print(f"  {listened:.1f}s", flush=True)
        out = HERE / "timing_manual.csv"
        write_timing(out, manual_rows)
        print(
            f"Wrote {out} total={sum(float(r['duration_s']) for r in manual_rows)/60:.2f} min",
            flush=True,
        )


if __name__ == "__main__":
    main()
