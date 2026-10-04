"""Software-validation integrity checks for SoftwarX §3 (I1, I2, duration).

I1 — revision race (Django + PostgreSQL):
  For each trial: submit extract job at revision R, edit segment bounds
  (bumps definition_revision to R+1 and clears current artifact), then call
  JobService.publish for the old job. Assert DB state: job=STALE and
  segment.current_artifact_id is None. This is a logical publish-after-revision
  race (not a wall-clock sleep, not HTTP). Publish uses select_for_update on
  segment then job and compares segment.definition_revision to
  job.expected_revision (apps.processing.services.job.JobService.publish).

I2 + duration — within-environment extract repeatability (no Django):
  On the N=20 local already-cut MP3 sample, run the same FFmpeg convert three
  times per segment (YouAudioLab codec: PCM s16le, 16 kHz, mono). Compare
  SHA-256 of the WAV bytes across the three runs. Duration error is
      E_i = |duration_wav_i - duration_requested_i|
  where duration_wav is nframes/framerate from the WAV header and
  duration_requested is end_sec - start_sec from the sample CSV
  (equals duration_s for this sample). Does NOT claim YouTube retrieval
  reproducibility.

Writes:
  integrity_race.csv / integrity_extract.csv / integrity_results.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_sample(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wav_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def run_extract(mp3: Path, wav: Path, duration_s: float, ffmpeg_bin: str) -> None:
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
    proc = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        shell=False,
    )
    if proc.returncode != 0 or not wav.is_file() or wav.stat().st_size == 0:
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        raise RuntimeError(err[-1000:])


def run_extract_repeatability(
    sample: Path,
    work_dir: Path,
    out_csv: Path,
    ffmpeg_bin: str,
    repeats: int,
) -> dict:
    rows = load_sample(sample)
    work_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    mismatches = 0
    errors: list[float] = []

    for row in rows:
        seg_id = row["segment_id"]
        mp3 = Path(row["audio_path"])
        requested = float(row["end_sec"]) - float(row["start_sec"])
        digests: list[str] = []
        durations: list[float] = []
        for run in range(1, repeats + 1):
            wav = work_dir / seg_id / f"run{run}.wav"
            run_extract(mp3, wav, float(row["duration_s"]), ffmpeg_bin)
            digest = sha256_file(wav)
            actual = wav_duration_s(wav)
            digests.append(digest)
            durations.append(actual)
            err = abs(actual - requested)
            errors.append(err)
            records.append(
                {
                    "segment_id": seg_id,
                    "run": run,
                    "requested_duration_s": f"{requested:.6f}",
                    "wav_duration_s": f"{actual:.6f}",
                    "abs_duration_error_s": f"{err:.6f}",
                    "sha256": digest,
                }
            )
        if len(set(digests)) != 1:
            mismatches += 1
        print(
            f"  {seg_id}: checksums={'OK' if len(set(digests)) == 1 else 'MISMATCH'} "
            f"E={statistics.mean(abs(d - requested) for d in durations):.4f}s"
        )

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "segment_id",
                "run",
                "requested_duration_s",
                "wav_duration_s",
                "abs_duration_error_s",
                "sha256",
            ],
        )
        writer.writeheader()
        writer.writerows(records)

    n_seg = len(rows)
    return {
        "n_segments": n_seg,
        "repeats": repeats,
        "checksum_identical_segments": n_seg - mismatches,
        "checksum_mismatches": mismatches,
        "mean_abs_duration_error_s": round(statistics.mean(errors), 4) if errors else None,
        "max_abs_duration_error_s": round(max(errors), 4) if errors else None,
        "csv": str(out_csv),
    }


def run_race_trials(n_trials: int, out_csv: Path) -> dict:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

    import django

    django.setup()

    from apps.core.storage import FakeStorage, set_storage_for_tests
    from apps.processing.models import ProcessingJob
    from apps.processing.services.job import JobService
    from apps.workspace.models import AppUser, VideoSource
    from apps.workspace.services.project import ProjectService
    from apps.workspace.services.segment import SegmentService
    from apps.workspace.services.source import SourceService

    storage = FakeStorage()
    set_storage_for_tests(storage)
    jobs = JobService(storage)
    segments = SegmentService()
    sources = SourceService()

    user = AppUser.objects.create(
        display_name="IntegrityRace",
        login_identifier=f"integrity-race-{utc_now()}",
        status=AppUser.Status.ACTIVE,
    )
    project = ProjectService().create(
        name=f"Integrity race {utc_now()}",
        owner_user_id=user.id,
        language="vi",
    )
    source = sources.import_source(
        project_id=project.id,
        youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        actor_user_id=user.id,
    )
    source.source_status = VideoSource.Status.READY
    source.duration_seconds = 10_000.0
    source.save(update_fields=["source_status", "duration_seconds", "updated_at"])

    records: list[dict] = []
    stale_publications = 0

    for i in range(1, n_trials + 1):
        segment = segments.create(
            source_id=source.id,
            actor_user_id=user.id,
            start_seconds=float(i),
            end_seconds=float(i) + 3.0,
        )
        job = jobs.submit(
            segment_id=segment.id,
            expected_definition_revision=segment.definition_revision,
            actor_user_id=user.id,
        )
        jobs.mark_running(job.id)
        segments.update(
            segment.id,
            actor_user_id=user.id,
            expected_definition_revision=segment.definition_revision,
            start_seconds=float(i) + 0.5,
            end_seconds=float(i) + 3.5,
        )
        storage_key = (
            f"projects/{job.project_id}/segments/{job.segment_id}/jobs/{job.id}/audio.wav"
        )
        storage.put(storage_key, b"WAV")
        published = jobs.publish(job.id, storage_key=storage_key)
        segment.refresh_from_db()
        ok = (
            published.status == ProcessingJob.Status.STALE
            and segment.current_artifact_id is None
        )
        if not ok:
            stale_publications += 1
        records.append(
            {
                "trial": i,
                "job_id": str(job.id),
                "job_status": published.status,
                "segment_revision_after": segment.definition_revision,
                "job_expected_revision": job.expected_revision,
                "current_artifact_id": str(segment.current_artifact_id or ""),
                "stale_publication": "0" if ok else "1",
            }
        )
        if i % 20 == 0:
            print(f"  race trials {i}/{n_trials}")

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "trial",
                "job_id",
                "job_status",
                "segment_revision_after",
                "job_expected_revision",
                "current_artifact_id",
                "stale_publication",
            ],
        )
        writer.writeheader()
        writer.writerows(records)

    set_storage_for_tests(None)
    return {
        "n_trials": n_trials,
        "stale_publications": stale_publications,
        "protocol": (
            "logical publish-after-revision: submit@R, bound-edit→R+1, late publish; "
            "assert job=STALE and current_artifact_id is None (DB state)"
        ),
        "check_location": "JobService.publish (select_for_update; expected_revision)",
        "csv": str(out_csv),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=HERE / "sample_segments.csv")
    parser.add_argument("--work-dir", type=Path, default=HERE / "_integrity_work")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--race-trials", type=int, default=100)
    parser.add_argument("--skip-race", action="store_true")
    parser.add_argument("--skip-extract", action="store_true")
    parser.add_argument("--out-json", type=Path, default=HERE / "integrity_results.json")
    args = parser.parse_args()

    results: dict = {"generated_at": utc_now()}

    if not args.skip_extract:
        print("I2 + duration: within-environment extract repeatability ...")
        results["extract"] = run_extract_repeatability(
            sample=args.sample,
            work_dir=args.work_dir,
            out_csv=HERE / "integrity_extract.csv",
            ffmpeg_bin=args.ffmpeg,
            repeats=args.repeats,
        )
        print(
            "  identical checksums: "
            f"{results['extract']['checksum_identical_segments']}/"
            f"{results['extract']['n_segments']}; "
            f"mean |E|={results['extract']['mean_abs_duration_error_s']}s; "
            f"max |E|={results['extract']['max_abs_duration_error_s']}s"
        )

    if not args.skip_race:
        print(f"I1: {args.race_trials} logical revision-race trials ...")
        results["race"] = run_race_trials(
            n_trials=args.race_trials,
            out_csv=HERE / "integrity_race.csv",
        )
        print(
            f"  stale publications: {results['race']['stale_publications']}/"
            f"{results['race']['n_trials']}"
        )

    args.out_json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
