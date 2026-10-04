# Timing experiment protocol (pilot N=20)

Pilot comparison of **manual transcription** vs **YouAudioLab extract + ASR + human review** on a fixed sample drawn from [`audio_manifest.csv`](../../../../audio_manifest.csv).

## Sample

```bash
python docs/software/eval/select_sample.py
```

Defaults: `--n 20 --seed 42 --min-s 8 --max-s 45`, manifest at `d:\researcher\audio_manifest.csv`.

Outputs:

- `sample_segments.csv` — selected rows (`segment_id`, URL, bounds, local `audio_path`)
- Empty templates: `timing_manual.csv`, `timing_tool_human.csv`, `machine_jobs.csv`

Do **not** change the sample mid-experiment. Re-run `select_sample.py` only to regenerate the same IDs.

## What is timed

| Condition | Timed | Not timed |
| --- | --- | --- |
| Manual | Hearing the local MP3 and typing the transcript in an external editor | Cutting, renaming, labelling, packaging an export |
| Tool / machine | Extract + recognition job wall time (sum of job durations from logs/DB) | Live YouTube download if the source is already cached |
| Tool / human | Reviewing and accepting/editing the ASR candidate in the workspace | Labelling and export |

One reviewer does both human conditions. Labelling may use a second person and is excluded from both timed columns.

## Manual condition

Attended-listen pilot (wall clock via `ffmpeg -re`, used for the SoftwareX redo):

```bash
python docs/software/eval/measure_human_listen.py --mode both
```

- Tool: one full realtime listen per segment with the ASR candidate available (`asr_candidates.csv`).
- Manual: two full realtime listens per segment (hear + type pass); typing is treated as concurrent on the second pass.

Finer editor-only stopwatch (optional):

```bash
python docs/software/eval/time_human_session.py --mode manual --open-audio
```

Or fill `timing_manual.csv` by hand (`duration_s`, or `started_at` + `ended_at` ISO-8601).

## Tool condition

### Machine time (agent path, no Docker required)

```bash
python docs/software/eval/run_machine_local.py --model-size base
```

Writes `machine_jobs.csv` and `asr_candidates.csv`. Extract is local MP3→16 kHz mono WAV with the same ffmpeg codec settings as YouAudioLab; ASR is faster-whisper (`vi`). No live YouTube download is timed.

### Machine time (full YouAudioLab stack, when Docker is up)

```bash
python docs/software/eval/seed_timing_project.py --email YOU@example.com --mark-ready
# queue extract + ASR in the UI or API, then:
python docs/software/eval/export_machine_jobs_from_db.py --project-id <uuid>
```

### Human review

```bash
python docs/software/eval/time_human_session.py --mode tool --open-audio
```

Or fill `timing_tool_human.csv` by hand while reviewing candidates from `asr_candidates.csv` in the workspace.

## Summarize

```bash
python docs/software/eval/summarize_timing.py
```

Writes `results.json` and prints Table-3-style totals. Exit code is non-zero until every human row and at least the machine job rows needed for a complete batch have durations.

## Figure 4

```bash
python docs/software/figures/figure4_review_time.py
```

Reads `docs/software/eval/results.json` (`figure4` keys). Refuses to draw if `ready` is false.

## Manuscript

After `results.json` is ready, update §3 Evaluation (EN + VI): N=20, audio minutes, video count, Table 3 numbers, Figure 4 caption, then rebuild with `build_manuscript.py`.
