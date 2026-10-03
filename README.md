# YouAudioLab

YouAudioLab is a web platform for building labelled speech datasets from YouTube
videos. A researcher imports a video, cuts time-bounded segments, extracts
checksummed audio, and optionally drafts a transcript with ASR. Human annotators
then label each segment. The owner can hide peer labels, measure agreement,
adjudicate a gold set, and export a snapshot that does not leak the same video
into both train and test.

It was built for speech and audio NLP research, where the scarce resource is a
corpus you can defend: known cuts, known annotators, and a holdout that is not
the same recording as the training set.

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Getting started](#getting-started)
- [Building a corpus](#building-a-corpus)
- [Export formats](#export-formats)
- [Data model](#data-model)
- [API reference](#api-reference)
- [Development](#development)
- [Known limitations](#known-limitations)
- [Reproducing the SoftwareX validation checks](#reproducing-the-softwarex-validation-checks)
- [License and data](#license-and-data)

## What it does

- Imports a YouTube URL, stores video metadata, and lets the owner define
  segments by start and end time. Changing the bounds bumps a definition
  revision so an old audio cut cannot be published as current.
- Extracts a WAV (PCM, 16 kHz, mono by default) with FFmpeg and records a
  checksum. ASR and AI suggestions stay as candidates until a person applies
  them to the canonical transcript.
- Gives annotators a workspace on one segment: listen, read the transcript,
  assign project labels. When blind mode is on, annotators see only their own
  episodes.
- Routes work through a queue (assign, start, complete, release). Overlap is
  how you get agreement: assign the same segment to more than one person.
- Reports Jaccard, Cohen’s κ, and Fleiss’ κ on Progress, plus a quality report
  of duration buckets and per-video coverage. The owner can save gold labels
  or adopt a majority.
- Exports a research snapshot (full episodes) and training views that use an
  explicit supervision policy. Splits are by source (the video), not by random
  segment.

ASR and AI keys stay on the account or system settings and are encrypted at
rest. Project settings only choose which provider and model to inherit.

## Architecture

```mermaid
flowchart TB
    Browser["Browser<br/>Bootstrap 5 + vanilla JS"]

    subgraph web["Django process"]
        Pages["Page views<br/>server-rendered HTML"]
        API["REST API<br/>Django REST Framework"]
    end

    DB[("PostgreSQL")]
    REDIS[("Redis<br/>Celery broker")]
    WORKER["Celery worker"]
    YT["yt-dlp"]
    FF["FFmpeg"]
    ASR["ASR<br/>local or OpenAI"]
    LLM["Ollama<br/>optional assist"]

    Browser --> Pages
    Browser --> API
    Pages --> DB
    API --> DB
    Pages -->|"queue a job"| REDIS
    API -->|"queue a job"| REDIS
    REDIS --> WORKER
    WORKER -->|"metadata, audio, ASR"| DB
    WORKER --> YT
    WORKER --> FF
    WORKER --> ASR
    WORKER --> LLM
```

Pages and the API share the same membership checks. Slow work — metadata,
audio extract, transcription — runs in Celery. A job stores the segment
revision it was started against. If the bounds change before publish, the job
becomes stale and does not replace the current artifact.

| Component | Choice |
|---|---|
| Framework | Django 6.1, Django REST Framework 3.18 |
| Database | PostgreSQL 16 |
| Task queue | Celery with a Redis broker |
| Media | yt-dlp + FFmpeg |
| Speech draft | Local Whisper-style ASR, or OpenAI |
| Assist | Ollama, optional and separate from ASR |
| Frontend | Bootstrap 5 and vanilla JavaScript |
| Languages | English and Vietnamese |
| Local ports | HTTP **8001**, Postgres **5433**, Redis **6381** |

## Getting started

You need Python 3.12–3.14, FFmpeg on `PATH`, and Docker if you want the bundled
Postgres and Redis.

```powershell
cd YouAudioLab_Django
copy .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
docker compose up -d db redis
```

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres. The Compose file publishes it on port 5433. |
| `REDIS_URL` / `CELERY_BROKER_URL` | Redis on port 6381. |
| `DJANGO_SECRET_KEY` | Signing key. Change it before any shared deployment. |
| `ASR_SECRETS_KEY` | Passphrase used to encrypt stored API keys. |
| `ASR_ADMIN_USER_IDS` | User UUIDs allowed to edit system ASR. Empty in development means every signed-in user. |
| `AI_ADMIN_USER_IDS` | Same rule for system AI. |
| `YTDLP_COOKIES_FILE` | Optional cookies file when YouTube requires a logged-in session. |

Then migrate, seed a system admin, and start the app (auto-reload) plus a worker:

```powershell
python manage.py migrate
python manage.py seed_admin --write-env
python manage.py runserver 8001
```

In a second terminal, with the same environment variables:

```powershell
celery -A config.celery worker --loglevel=info --pool=solo
```

Restart the server after `--write-env` so the admin UUIDs in `.env` load.
Default seed login is `admin` / `ChangeMe-admin1`. Change that password.
The app is at **<http://localhost:8001/identity/>**. Health:
**<http://localhost:8001/api/v1/health>**.

Docker can run the whole stack (`docker compose up --build`) on the same ports.
That image does not reload when you edit source; use `runserver` while developing.

## Building a corpus

**Create a project and its protocol.** Project settings hold the audio defaults
(WAV / PCM / 16 kHz / mono), the readiness gates (Audio OK, transcript,
annotation), blind labelling, and the corpus license plus consent notes. Those
notes are copied into exports and the quality report.

**Define labels, then attach them to the project.** A label can carry a
description and include/exclude guidance. Annotators apply project labels to a
whole segment, not to words inside the transcript.

**Add members.** Owners edit cuts, gold, export, and quality. Annotators label.
System ASR and system AI are a separate allowlist (`ASR_ADMIN_USER_IDS`,
`AI_ADMIN_USER_IDS`), not the project owner role.

**Import a video and cut segments.** Paste a YouTube URL. Metadata is fetched
in the background. On the source, create segments with start and end times.
Queue extract audio. When a verified artifact exists, generate a transcript;
apply it to the canonical text only if you accept it.

**Assign and label.** The work queue sends segments to people. In the workspace,
assign a label. With blind mode on, an annotator cannot open everyone else’s
episodes or see their names on the segment index.

**Review agreement and gold.** Progress shows overlap, mean Jaccard, exact
match, Cohen’s κ, and Fleiss’ κ, plus label balance. Quality adds duration
buckets and one row per video (annotated, gold, overlap, ready, and the
by-source split). On a segment, the owner saves gold labels or adopts the
majority. Annotators never see gold.

**Export.** Pick a format, a supervision policy, and a split. Research JSON
keeps every episode. Training formats use `supervised_labels`. Prefer
`by_source` so one video stays in a single fold.

## Export formats

Formats are views of one snapshot. The unit is the segment.

**Research snapshot**

| Key | File | Notes |
|---|---|---|
| `json` | `.json` | Full document: segments, annotation episodes, assignments, ASR runs, AI assists, split, supervision, `content_hash`. |
| `jsonl` | `.jsonl` | The same segment records, one object per line. |
| `dataset_zip` | `.zip` | Audio from the current verified artifact, CSV metadata, and a README. `storage_key` is not in the public JSON. |

**Training**

| Key | File | Notes |
|---|---|---|
| `hf_jsonl` | `.jsonl` | Text classification for Hugging Face. First line is label metadata. |
| `spacy_json` | `.json` | Document categories. Entity spans are empty; labels cover the whole segment. |
| `json_llm` | `.jsonl` | Chat `messages` for fine-tuning. |

**Other tools and spreadsheets**

| Key | File | Notes |
|---|---|---|
| `doccano_jsonl` | `.jsonl` | Text classification, not token spans. |
| `label_studio_json` | `.json` | Choices on the transcript. |
| `json_segments` | `.json` | Transcript plus supervised labels. |
| `xml` | `.xml` | Segment tree. |
| `csv_segments` | `.csv` | One row per segment. UTF-8 with BOM. |
| `csv_annotations` | `.csv` | One row per human episode, for recomputing agreement. |
| `csv_assignments` | `.csv` | Work-queue rows, separate from labels. |
| `xlsx` | `.xlsx` | Workbook for review. Prefer CSV on large projects. |

### Supervision and splits

Training views collapse active episodes with a policy:

| Policy | Rule |
|---|---|
| `majority` | Label kept when a strict majority of annotators on that segment have it. Default. |
| `union` | Every active label name. |
| `intersection` | Only labels every such annotator has. |
| `first_annotator` | Active labels of the earliest episode. |
| `gold` | Owner adjudication when present; otherwise majority. |

`by_source` shuffles videos with a seed (default 42) and assigns each video to
train, val, or test (default 0.8 / 0.1 / 0.1). Every segment inherits its
video’s split. A single video in the export is placed entirely in train and
the snapshot records a warning. `content_hash` ignores `exported_at`.

`ready_only` keeps segments that pass the project’s readiness gates.

## Data model

**Corpus**

| Model | Description |
|---|---|
| `Project` | A study, with language, status, license, and consent notes |
| `ProjectSettings` | Audio defaults, readiness gates, blind flag, project ASR/AI overrides |
| `ProjectMembership` | `OWNER` or `ANNOTATOR` |
| `VideoSource` | One YouTube video and its metadata snapshot |
| `AudioSegment` | Time bounds, revision, canonical transcript, current artifact |
| `Label` / `ProjectLabel` | A category and its attachment to a project, with optional display overrides |

**Annotation**

| Model | Description |
|---|---|
| `SegmentAnnotation` | One person’s active label on a segment. Soft-removed with `removed_at`. |
| `SegmentGoldLabel` | Owner-adjudicated label. Hidden from annotators. |
| `AnnotationAssignment` | Work-queue item. Completion is not gold. |
| `AssignmentBatch` | Owner action that created a group of assignments |

**Processing**

| Model | Description |
|---|---|
| `ProcessingJob` | Extract or transcribe job, with the revision it expected |
| `ProcessingArtifact` | Checksummed audio file |
| `AsrRun` | Immutable ASR candidate; apply copies text onto the transcript |
| `AiAssistRun` | Optional cleanup or label suggestion |

The source of truth for human labels is `SegmentAnnotation`. `supervised_labels`
and `gold_labels` are computed at export time. They are not a second copy that
annotators edit.

## API reference

Base path `/api/v1/`. HTML uses a session after login. The API uses
`Authorization: Bearer`. A legacy `X-User-Id` header is accepted only in
development and test.

### Pages

| Method | Path | Description | Access |
|---|---|---|---|
| GET, POST | `/identity/` | Sign in and register | Public |
| GET | `/projects/` | Your projects | Authenticated |
| GET | `/projects/<id>/` | Overview | Member |
| GET | `/projects/<id>/progress/` | Pipeline, IAA, label balance | Member; IAA is owner-only |
| GET | `/projects/<id>/quality/` | Duration and per-video coverage | Owner |
| GET | `/projects/<id>/work-queue/` | Assignments | Member |
| GET | `/projects/<id>/sources/` | Videos | Member |
| GET | `/projects/<id>/segments/` | Segment index | Member; blind hides peer labels |
| GET | `/projects/<id>/segments/<id>/` | Workspace | Member |
| GET, POST | `/projects/<id>/labels/` | Project labels | Member; writes are owner |
| GET, POST | `/projects/<id>/members/` | Membership | Member; writes are owner |
| GET, POST | `/projects/<id>/settings/` | Protocol, ethics, ASR/AI inherit | Member; writes are owner |
| GET, POST | `/projects/<id>/export/` | Download a snapshot | Owner |
| GET, POST | `/settings/` | Account, personal ASR/AI, system defaults | Authenticated; system tabs need admin IDs |

### Projects, sources, segments

| Method | Path | Description | Access |
|---|---|---|---|
| POST | `/api/v1/auth/register`, `/auth/login` | Register and login | Public |
| GET | `/api/v1/me` | Current user | Authenticated |
| GET, POST | `/api/v1/projects` | List or create | Authenticated |
| GET, PATCH | `/api/v1/projects/<id>` | Read or update, including license and consent | Member / owner |
| GET, PUT | `/api/v1/projects/<id>/settings` | Readiness, blind, audio, ASR/AI overrides | Member / owner |
| GET, POST | `/api/v1/projects/<id>/sources` | Import a YouTube URL | Member / owner |
| POST | `.../sources/<id>/refresh-metadata` | Queue metadata | Owner |
| GET, POST | `.../sources/<id>/segments` | List or create cuts | Member / owner |
| GET, PATCH, DELETE | `/api/v1/segments/<id>` | Read, revise bounds or transcript, soft-delete | Member / owner |

### Annotation, agreement inputs, export

| Method | Path | Description | Access |
|---|---|---|---|
| GET, POST | `/api/v1/segments/<id>/annotations` | List or assign. Annotators see only their rows when blind is on. | Member |
| DELETE | `/api/v1/annotations/<id>` | Soft-remove an episode | Owner, or the annotator |
| GET, POST | `/api/v1/projects/<id>/assignments` | Work queue | Member / owner |
| GET | `/api/v1/export-formats` | Format catalogue | Authenticated |
| GET | `/api/v1/projects/<id>/export` | Render a snapshot. Query: format, split, supervision, `ready_only`. | Owner |
| GET | `/api/v1/projects/<id>/quality-report` | Same document as the quality page | Owner |
| GET | `/api/v1/health` | Health check | Public |

Jobs, ASR runs, and AI assists live under `/api/v1/segments/<id>/jobs`,
`/asr/`, and `/ai/`. System default endpoints are
`/api/v1/system/asr/defaults` and `/api/v1/system/ai/defaults`.

## Development

```
config/                 Django settings, URLs, Celery
apps/core/              Errors, auth helpers, storage port, YouTube id parse
apps/workspace/         Projects, segments, labels, annotation, export, quality
  services/             Domain logic (export, agreement, gold, readiness, …)
  management/commands/  seed_admin
apps/processing/        Jobs, artifacts, ASR, AI assist, media pipeline
templates/              Bootstrap 5 pages
static/                 CSS and JavaScript
docs/                   Design notes (export, QC, architecture)
tests/                  pytest
```

```powershell
$env:DATABASE_URL="postgresql://youaudiolab:youaudiolab@localhost:5433/youaudiolab_django"
pytest
```

Further design notes: [architecture](docs/architecture.md),
[export schema](docs/gate-ex1-research-dataset-export-design.md),
[splits and supervision](docs/gate-ex3-ml-export-splits.md),
[blind and IAA](docs/gate-qc1-blind-iaa-progress.md),
[quality report](docs/gate-qc2-quality-report.md).

## Known limitations

- There is no token-level or BIO labelling. A label applies to the whole
  segment. Sequence-tagging exports from other tools are intentionally absent.
- Agreement is multi-label set overlap plus per-label Cohen/Fleiss on presence,
  not Krippendorff’s alpha.
- Gold is a label set the owner saves. It is not a separate adjudication
  workflow with a conflict queue.
- YouTube download depends on yt-dlp and, for some videos, a cookies file.
  Quota and availability are outside this app.
- Celery does not reload when you edit task code. Restart the worker.
- Only PostgreSQL is supported for the constraint and race tests.

## Reproducing the SoftwareX validation checks

The SoftwareX manuscript (`docs/softwarex/YouAudioLab_SoftwareX.md`) reports a
software-validation case, not an ASR benchmark. The integrity checks map to
three invariants:

| Invariant | What to verify | Manuscript evidence |
| --- | --- | --- |
| I1 Revision consistency | An extract job started against an older `definition_revision` must not become the segment’s current artifact | 0/100 stale publications in race trials |
| I2 Artifact integrity | Repeated extracts with the same bounds and configuration yield the same SHA-256 on the stored WAV | 20 segments × 3 runs, 0 mismatches |
| I3 Dataset provenance | Blind dual annotation retains both rows; `by_source` export places each video in exactly one fold | 0 overwrites; 0 shared videos across train/test |

Automated coverage for the same mechanisms lives under `tests/` (processing
publish/stale paths, export snapshot `content_hash`, quality/split helpers). A
minimal local reproduction:

1. Follow [Getting started](#getting-started): PostgreSQL 16, Redis, FFmpeg on
   `PATH`, Python 3.12+, then run the Django app and a Celery worker.
2. Create a project, import local waveform sources (or a YouTube URL as in the
   manuscript illustrative workflow), define segments, and queue extract jobs.
3. Confirm that editing segment bounds increments `definition_revision` and that
   an in-flight job with a mismatched `expected_revision` ends as `STALE`
   without replacing the current artifact.
4. Re-run extract on a fixed set of segments and compare `ProcessingArtifact.checksum`
   (SHA-256 of waveform bytes). The dataset `content_hash` on an export is a
   separate digest over canonicalised snapshot metadata and ignores
   `exported_at`.
5. Export with `by_source`, seed 42, ratios `0.8 / 0.1 / 0.1`, and check that no
   source video appears in both train and test.

The timed 80-segment batch (56 min machine + 100 min human review) and the
candidate–accepted edit rates in the manuscript were recorded outside this
repository’s automated suite. Under the shipped code, recognition requires a
current verified artifact; recompute edit rates only on segments that have both
a verified artifact and an `AsrRun`.

Version **0.1.0** does not yet include a software licence file in this tree
(see [License and data](#license-and-data)). Before a journal release, add a
`LICENSE`, tag `v0.1.0`, and point metadata C2/C4/C8 at that tagged tree.

## License and data

Source repository: [https://github.com/ndung768/YouAudioLab](https://github.com/ndung768/YouAudioLab)

The application source does not yet ship with a published software licence in
this tree.

**A software licence would not cover the recordings you collect.** Audio and
transcripts taken from YouTube remain subject to YouTube’s terms and to the
speakers’ rights. In Vietnam, personal data in a corpus is also subject to
Decree 13/2023/ND-CP. Record the licence you intend to publish under, and the
consent you actually have, in project settings. Those fields are written into
the snapshot and the quality report so a later reader can see them next to the
files.

Maintained by Quoc-Dung Nguyen · nguyenquocdung@pyu.edu.vn