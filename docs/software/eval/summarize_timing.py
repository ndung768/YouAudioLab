"""Summarize timing CSVs into results.json for Table 3 / Figure 4."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S.%f",
)


def parse_ts(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1]
    for fmt in ISO_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_duration_s(row: dict[str, str]) -> float | None:
    raw = (row.get("duration_s") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            return None
    start = parse_ts(row.get("started_at", ""))
    end = parse_ts(row.get("ended_at", ""))
    if start and end and end >= start:
        return (end - start).total_seconds()
    finished = parse_ts(row.get("finished_at", ""))
    if start and finished and finished >= start:
        return (finished - start).total_seconds()
    return None


def read_human_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"Missing file: {path}")
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for row in rows:
        seg = (row.get("segment_id") or "").strip()
        if not seg:
            continue
        dur = parse_duration_s(row)
        out.append(
            {
                "segment_id": seg,
                "duration_s": dur,
                "notes": (row.get("notes") or "").strip(),
                "complete": dur is not None and dur >= 0,
            }
        )
    return out


def read_machine_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"Missing file: {path}")
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for row in rows:
        seg = (row.get("segment_id") or "").strip()
        job_type = (row.get("job_type") or "").strip()
        if not seg and not job_type:
            continue
        dur = parse_duration_s(row)
        status = (row.get("status") or "").strip()
        out.append(
            {
                "job_id": (row.get("job_id") or "").strip(),
                "segment_id": seg,
                "job_type": job_type,
                "duration_s": dur,
                "status": status,
                "notes": (row.get("notes") or "").strip(),
                "complete": dur is not None and dur >= 0,
            }
        )
    return out


def minutes(seconds: float) -> float:
    return round(seconds / 60.0, 2)


def summarize(
    manual: list[dict],
    tool_human: list[dict],
    machine: list[dict],
    sample_path: Path | None,
) -> dict:
    manual_done = [r for r in manual if r["complete"]]
    tool_done = [r for r in tool_human if r["complete"]]
    machine_done = [r for r in machine if r["complete"]]

    manual_total_s = sum(float(r["duration_s"]) for r in manual_done)
    tool_human_total_s = sum(float(r["duration_s"]) for r in tool_done)
    machine_total_s = sum(float(r["duration_s"]) for r in machine_done)

    n_manual = len(manual_done)
    n_tool = len(tool_done)
    n_machine_jobs = len(machine_done)

    sample_meta: dict = {}
    if sample_path and sample_path.is_file():
        with sample_path.open(encoding="utf-8", newline="") as fh:
            sample_rows = list(csv.DictReader(fh))
        durations = [float(r["duration_s"]) for r in sample_rows if r.get("duration_s")]
        sample_meta = {
            "n_segments": len(sample_rows),
            "audio_seconds": round(sum(durations), 3) if durations else 0.0,
            "audio_minutes": minutes(sum(durations)) if durations else 0.0,
            "mean_segment_s": round(sum(durations) / len(durations), 2) if durations else 0.0,
            "n_videos": len({r.get("video_id") for r in sample_rows if r.get("video_id")}),
            "segment_ids": [r["segment_id"] for r in sample_rows if r.get("segment_id")],
        }

    incomplete = {
        "manual_missing": [r["segment_id"] for r in manual if not r["complete"]],
        "tool_human_missing": [r["segment_id"] for r in tool_human if not r["complete"]],
        "machine_missing_rows": sum(1 for r in machine if not r["complete"]),
    }

    ready = (
        n_manual > 0
        and n_tool > 0
        and n_machine_jobs > 0
        and not incomplete["manual_missing"]
        and not incomplete["tool_human_missing"]
    )

    machine_min = minutes(machine_total_s) if n_machine_jobs else None
    tool_human_min = minutes(tool_human_total_s) if n_tool else None
    manual_min = minutes(manual_total_s) if n_manual else None
    batch_min = (
        round(machine_min + tool_human_min, 2)
        if machine_min is not None and tool_human_min is not None
        else None
    )

    result = {
        "ready": ready,
        "sample": sample_meta,
        "manual": {
            "n": n_manual,
            "total_seconds": round(manual_total_s, 3),
            "total_minutes": manual_min,
            "mean_seconds_per_segment": round(manual_total_s / n_manual, 2) if n_manual else None,
        },
        "tool_human": {
            "n": n_tool,
            "total_seconds": round(tool_human_total_s, 3),
            "total_minutes": tool_human_min,
            "mean_seconds_per_segment": round(tool_human_total_s / n_tool, 2) if n_tool else None,
        },
        "machine": {
            "n_jobs": n_machine_jobs,
            "total_seconds": round(machine_total_s, 3),
            "total_minutes": machine_min,
            "by_type": {},
        },
        "figure4": {
            "manual_human_minutes": manual_min,
            "tool_human_minutes": tool_human_min,
            "machine_minutes": machine_min,
            "batch_total_minutes": batch_min,
        },
        "throughput": {
            "machine_segments_per_hour": None,
        },
        "incomplete": incomplete,
    }

    by_type: dict[str, dict] = {}
    for row in machine_done:
        key = row["job_type"] or "unknown"
        bucket = by_type.setdefault(key, {"n": 0, "total_seconds": 0.0})
        bucket["n"] += 1
        bucket["total_seconds"] += float(row["duration_s"])
    for key, bucket in by_type.items():
        bucket["total_seconds"] = round(bucket["total_seconds"], 3)
        bucket["total_minutes"] = minutes(bucket["total_seconds"])
    result["machine"]["by_type"] = by_type

    n_segments = sample_meta.get("n_segments") or n_tool or n_manual
    if machine_min and machine_min > 0 and n_segments:
        result["throughput"]["machine_segments_per_hour"] = round(
            n_segments / (machine_min / 60.0), 1
        )

    return result


def print_table(result: dict) -> None:
    fig = result["figure4"]
    print("=== Timing summary ===")
    print(f"ready: {result['ready']}")
    sample = result.get("sample") or {}
    if sample:
        print(
            f"sample: N={sample.get('n_segments')} "
            f"audio_min={sample.get('audio_minutes')} "
            f"videos={sample.get('n_videos')}"
        )
    print(
        f"Manual human: {fig.get('manual_human_minutes')} min "
        f"(mean {result['manual'].get('mean_seconds_per_segment')} s/seg, "
        f"n={result['manual']['n']})"
    )
    print(
        f"Tool human:   {fig.get('tool_human_minutes')} min "
        f"(mean {result['tool_human'].get('mean_seconds_per_segment')} s/seg, "
        f"n={result['tool_human']['n']})"
    )
    print(
        f"Machine:      {fig.get('machine_minutes')} min "
        f"(jobs={result['machine']['n_jobs']})"
    )
    print(f"Batch total:  {fig.get('batch_total_minutes')} min")
    thr = result["throughput"].get("machine_segments_per_hour")
    if thr is not None:
        print(f"Machine throughput: {thr} segments/hour")
    inc = result["incomplete"]
    if inc["manual_missing"] or inc["tool_human_missing"] or inc["machine_missing_rows"]:
        print("incomplete:")
        if inc["manual_missing"]:
            print(f"  manual_missing={inc['manual_missing']}")
        if inc["tool_human_missing"]:
            print(f"  tool_human_missing={inc['tool_human_missing']}")
        if inc["machine_missing_rows"]:
            print(f"  machine_missing_rows={inc['machine_missing_rows']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual", type=Path, default=HERE / "timing_manual.csv")
    parser.add_argument("--tool-human", type=Path, default=HERE / "timing_tool_human.csv")
    parser.add_argument("--machine", type=Path, default=HERE / "machine_jobs.csv")
    parser.add_argument("--sample", type=Path, default=HERE / "sample_segments.csv")
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Exit 0 even when human CSVs are incomplete (machine-only pilot).",
    )
    args = parser.parse_args()

    result = summarize(
        read_human_csv(args.manual),
        read_human_csv(args.tool_human),
        read_machine_csv(args.machine),
        args.sample,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print_table(result)
    print(f"Wrote {args.out}")
    if not result["ready"] and not args.allow_partial:
        raise SystemExit(
            "Timing CSVs are incomplete; fill duration_s (or started_at/ended_at) "
            "before updating the manuscript numbers. Use --allow-partial for machine-only."
        )


if __name__ == "__main__":
    main()
