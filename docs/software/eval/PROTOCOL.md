# Timing experiment protocol (pilot N=20)

Pilot measurement of **YouAudioLab extract + ASR** (and, when filled by a
human reviewer, manual transcription vs tool review) on a fixed sample from
[`audio_manifest.csv`](../../../../audio_manifest.csv).

Human stopwatch rows must come from a real editor session
(`time_human_session.py` or hand-filled CSV). Do **not** invent human times
from audio duration or automated playback.

## Sample

```bash
python docs/software/eval/select_sample.py
```

Defaults: `--n 20 --seed 42 --min-s 8 --max-s 45`, manifest at
`d:\researcher\audio_manifest.csv`.

Outputs:

- `sample_segments.csv` — selected rows
- Empty templates: `timing_manual.csv`, `timing_tool_human.csv`, `machine_jobs.csv`

Do **not** change the sample mid-experiment.

## What is timed

| Condition | Timed | Not timed |
| --- | --- | --- |
| Manual | Hearing the local MP3 and typing the transcript in an external editor | Cutting, renaming, labelling, packaging an export |
| Tool / machine | Extract + recognition job wall time | Live YouTube download if the source is already cached |
| Tool / human | Reviewing and accepting/editing the ASR candidate in the workspace | Labelling and export |

## Manual / tool-human (real stopwatch only)

```bash
python docs/software/eval/time_human_session.py --mode manual --open-audio
python docs/software/eval/time_human_session.py --mode tool --open-audio
```

Or fill `timing_manual.csv` / `timing_tool_human.csv` by hand (`duration_s`, or
`started_at` + `ended_at` ISO-8601).

## Machine

```bash
python docs/software/eval/run_machine_local.py --model-size base
```

Writes `machine_jobs.csv` and `asr_candidates.csv`. Extract is local MP3→16 kHz
mono WAV with YouAudioLab codec settings; ASR is faster-whisper (`vi`).

With Docker up:

```bash
python docs/software/eval/seed_timing_project.py --email YOU@example.com --mark-ready
python docs/software/eval/export_machine_jobs_from_db.py --project-id <uuid>
```

## Summarize / figure

```bash
python docs/software/eval/summarize_timing.py --allow-partial   # machine-only OK
python docs/software/figures/figure4_review_time.py
```

`results.json` is `ready: true` only when both human CSVs are complete. Until
then Figure 4 draws the machine-only pilot breakdown.

## Integrity (I1 stale-publication, I2-B extract repeatability, duration \(E_i\))

```bash
python docs/software/eval/run_integrity_checks.py
```

Writes `integrity_race.csv`, `integrity_extract.csv`, `integrity_results.json`.
Requires PostgreSQL for the stale-publication block (same DB as local Docker).
I1 includes sequential publish-after-revision rejection plus a two-transaction
publish-vs-bound-edit race under `select_for_update`
(`tests/test_jobs_races.py`; barrier-synchronized DB transactions, not a Celery
multi-worker stress test). ASR stale completion and late-apply rejection are
covered by `tests/test_asr_stale.py`. Redistributable synthetic WAVs for
invariant tests (without the copyrighted pilot MP3s) live in
`docs/software/eval/fixtures/`. Host/container pins are recorded in
`ENVIRONMENT.md`. Duration error is
\(|t_{wav}-(t_{end}-t_{start})|\) from the WAV header; extract repeatability
(I2-B) is within-environment only (local MP3 → WAV), not live YouTube. I2-A
re-reads storage after `JobService.publish` and asserts
`artifact.checksum == SHA-256(re-read bytes)` (`integrity_i2a.csv`).

## Manuscript

Update §3 only with numbers that appear in `results.json` and
`integrity_results.json`. Do not paste placeholder human minutes. Abstract
and body must use the same N (20), not a residual larger count.
