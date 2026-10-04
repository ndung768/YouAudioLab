"""Run extract+ASR on the pilot sample without a live Django/DB stack.

Uses local MP3 clips from sample_segments.csv (already cut; no YouTube download).
Extract = ffmpeg normalize to 16 kHz mono WAV (same flags as apps.processing.media.cut_segment_audio).
ASR = faster-whisper, language vi (same engine family as YouAudioLab local recogniser).

Writes machine_jobs.csv with real wall-clock durations.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fmt(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def load_sample(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def run_extract(mp3: Path, wav: Path, duration_s: float, ffmpeg_bin: str) -> float:
    """Convert the already-cut clip to pipeline WAV; time the ffmpeg call."""
    wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        "0.000",
        "-to",
        f"{max(duration_s, 0.05):.3f}",
        "-i",
        str(mp3),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(wav),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        shell=False,
    )
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0 or not wav.is_file() or wav.stat().st_size == 0:
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        raise RuntimeError(err[-1000:])
    return elapsed


def run_asr(model, wav: Path) -> tuple[float, str]:
    t0 = time.perf_counter()
    segments_iter, _info = model.transcribe(
        str(wav),
        language="vi",
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        temperature=0.0,
    )
    parts = [seg.text.strip() for seg in segments_iter if seg.text and seg.text.strip()]
    text = " ".join(parts).strip()
    return time.perf_counter() - t0, text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=HERE / "sample_segments.csv")
    parser.add_argument("--out", type=Path, default=HERE / "machine_jobs.csv")
    parser.add_argument("--work-dir", type=Path, default=HERE / "_machine_work")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--model-size", default="base")
    parser.add_argument(
        "--model-cache",
        type=Path,
        default=REPO / "storage" / "whisper-models",
    )
    parser.add_argument(
        "--transcripts-out",
        type=Path,
        default=HERE / "asr_candidates.csv",
    )
    args = parser.parse_args()

    rows = load_sample(args.sample)
    if not rows:
        raise SystemExit(f"No rows in {args.sample}")

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit("faster-whisper is not installed in this environment") from exc

    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.model_cache.mkdir(parents=True, exist_ok=True)
    print(f"Loading faster-whisper model={args.model_size} ...")
    model = WhisperModel(
        args.model_size,
        device="cpu",
        compute_type="int8",
        download_root=str(args.model_cache),
    )

    job_rows: list[dict[str, str]] = []
    transcript_rows: list[dict[str, str]] = []

    for row in rows:
        seg_id = row["segment_id"]
        mp3 = Path(row["audio_path"])
        duration_s = float(row["duration_s"])
        if not mp3.is_file():
            raise SystemExit(f"Missing audio: {mp3}")

        wav = args.work_dir / f"{seg_id}.wav"

        started = utc_now()
        try:
            extract_s = run_extract(mp3, wav, duration_s, args.ffmpeg)
            status_extract = "SUCCEEDED"
            notes_extract = "local mp3→wav (YouAudioLab extract codec settings); no YouTube download"
        except Exception as exc:  # noqa: BLE001
            extract_s = 0.0
            status_extract = "FAILED"
            notes_extract = str(exc)[:500]
        finished = utc_now()
        job_rows.append(
            {
                "job_id": f"local-extract-{seg_id}",
                "segment_id": seg_id,
                "job_type": "extract",
                "queued_at": fmt(started),
                "started_at": fmt(started),
                "finished_at": fmt(finished),
                "duration_s": f"{extract_s:.3f}",
                "status": status_extract,
                "notes": notes_extract,
            }
        )

        if status_extract != "SUCCEEDED":
            job_rows.append(
                {
                    "job_id": f"local-asr-{seg_id}",
                    "segment_id": seg_id,
                    "job_type": "asr",
                    "queued_at": "",
                    "started_at": "",
                    "finished_at": "",
                    "duration_s": "",
                    "status": "SKIPPED",
                    "notes": "extract failed",
                }
            )
            print(f"{seg_id}: extract FAILED")
            continue

        started = utc_now()
        try:
            asr_s, text = run_asr(model, wav)
            status_asr = "SUCCEEDED"
            notes_asr = f"faster-whisper {args.model_size} language=vi"
        except Exception as exc:  # noqa: BLE001
            asr_s = 0.0
            text = ""
            status_asr = "FAILED"
            notes_asr = str(exc)[:500]
        finished = utc_now()
        job_rows.append(
            {
                "job_id": f"local-asr-{seg_id}",
                "segment_id": seg_id,
                "job_type": "asr",
                "queued_at": fmt(started),
                "started_at": fmt(started),
                "finished_at": fmt(finished),
                "duration_s": f"{asr_s:.3f}",
                "status": status_asr,
                "notes": notes_asr,
            }
        )
        transcript_rows.append(
            {
                "segment_id": seg_id,
                "audio_path": str(mp3),
                "duration_s": f"{duration_s:.3f}",
                "asr_text": text,
                "asr_status": status_asr,
            }
        )
        print(f"{seg_id}: extract={extract_s:.2f}s asr={asr_s:.2f}s status={status_asr}")

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
        writer.writerows(job_rows)

    with args.transcripts_out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["segment_id", "audio_path", "duration_s", "asr_text", "asr_status"],
        )
        writer.writeheader()
        writer.writerows(transcript_rows)

    ok_extract = sum(1 for r in job_rows if r["job_type"] == "extract" and r["status"] == "SUCCEEDED")
    ok_asr = sum(1 for r in job_rows if r["job_type"] == "asr" and r["status"] == "SUCCEEDED")
    total_s = sum(float(r["duration_s"]) for r in job_rows if r["duration_s"])
    print(f"Wrote {args.out}")
    print(f"Wrote {args.transcripts_out}")
    print(
        f"extract_ok={ok_extract}/{len(rows)} asr_ok={ok_asr}/{len(rows)} "
        f"machine_total_s={total_s:.1f} ({total_s / 60:.2f} min)"
    )


if __name__ == "__main__":
    main()
