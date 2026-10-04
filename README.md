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
- [Example](#example)
- [Building a corpus](#building-a-corpus)
- [Export formats](#export-formats)
- [Data model](#data-model)
- [API reference](#api-reference)
- [Development](#development)
- [Known limitations](#known-limitations)
- [License and data](#license-and-data)

## What it does

- Imports a YouTube URL, stores video metadata, and lets the owner define
  segments by start and end time. Changing the bounds bumps a definition
  revision so an old audio cut cannot be published as current.
- Extracts a WAV (PCM, 16 kHz, mono by default) with FFmpeg and records a
  checksum. ASR and AI suggestions stay as candidates until a person applies
  them to the canonical transcript.
- Gives annotators a workspace on one segment: listen, read the transcript,
  assign project labels to the whole clip, or select a word or phrase in the
  transcript and label that text. When blind mode is on, annotators see only
  their own episodes and spans.
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
| `JWT_SECRET` | Signs API Bearer tokens (HTML pages use the session cookie). |
| `STORAGE_ROOT` | Local file store for source cache and checksummed WAVs. |
| `ASR_ENGINE` | Local engine name (`fake` in `.env.example`; use `faster-whisper` when installed). |
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

## Example

A full walk-through of one YouTube cut—protocol, extract, ASR apply, dual
annotation with optional text spans, and a `by_source` export—is in
**[docs/EXAMPLE.md](docs/EXAMPLE.md)** (with UI screenshots).

SoftwareX manuscript drafts, figures, and the timing-eval protocol live under
**[docs/software/](docs/software/)**. The article links to the Example walk-through
instead of repeating it.

## Building a corpus

**Create a project and its protocol.** Project settings hold the audio defaults
(WAV / PCM / 16 kHz / mono), the readiness gates (Audio OK, transcript,
annotation), blind labelling, and the corpus license plus consent notes. Those
notes are copied into exports and the quality report.

**Define labels, then attach them to the project.** A label can carry a
description and include/exclude guidance. Each project label has a
`LabelScope`: `SEGMENT` (whole clip, for example `Miền bắc`), `SPAN` (text in
the accepted transcript, for example `toxic` on the word `dm`), or `BOTH`. The
workspace shows segment-scope labels as clip chips and span-scope labels in the
phrase bar after you drag across words. Span rows are stored as
`TranscriptSpan` (character offsets + quote). Changing the accepted transcript
marks existing spans stale. Agreement, gold, and `supervised_labels` use
segment-scope labels only; spans travel in the research export and `spans.csv`.

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

Formats are views of one snapshot. The unit is the segment. Research and training
payloads declare `export_schema` = `youaudiolab.research_dataset` and
`export_schema_version` = **1.2** (label `scope`, per-segment `text_spans`, and
`spans.csv` in the zip).

**Research snapshot**

| Key | File | Notes |
|---|---|---|
| `json` | `.json` | Full document: segments, annotation episodes, `text_spans`, video description, assignments, ASR runs, AI assists, split, supervision, `content_hash`. |
| `jsonl` | `.jsonl` | The same segment records, one object per line. |
| `dataset_zip` | `.zip` | Verified audio under `audio/`, `metadata.csv`, `spans.csv` (YouTube link, times, title, description, transcript, span label), and a README. |

**Training**

| Key | File | Notes |
|---|---|---|
| `hf_jsonl` | `.jsonl` | Text classification plus `spans` for in-transcript labels. |
| `spacy_json` | `.json` | Document categories and entity spans from in-transcript labels. |
| `json_llm` | `.jsonl` | Chat `messages` for fine-tuning. |

**Other tools and spreadsheets**

| Key | File | Notes |
|---|---|---|
| `doccano_jsonl` | `.jsonl` | Segment text classification. Token spans are in the research export and `spans.csv`. |
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
| `AppUser` | Account used for membership, annotation, and admin allowlists |
| `Project` | A study, with language, status, license, and consent notes |
| `ProjectSettings` | Audio defaults, readiness gates, blind flag, project ASR/AI overrides |
| `ProjectMembership` | `OWNER` or `ANNOTATOR` |
| `VideoSource` | One YouTube video and its metadata snapshot |
| `AudioSegment` | Time bounds, `definition_revision`, canonical transcript, current artifact |
| `Label` / `ProjectLabel` | Catalog label and project attachment; `LabelScope` is `SEGMENT`, `SPAN`, or `BOTH` |

**Annotation**

| Model | Description |
|---|---|
| `SegmentAnnotation` | One person’s active whole-segment label. Soft-removed with `removed_at`. |
| `TranscriptSpan` | One person’s label on a character span of the accepted transcript (`start_char` / `end_char` / `quote`). Soft-removed or marked `stale` when the transcript changes. |
| `SegmentGoldLabel` | Owner-adjudicated segment-scope label. Hidden from annotators. |
| `AnnotationAssignment` | Work-queue item. Completion is not gold. |
| `AssignmentBatch` | Owner action that created a group of assignments |

**Processing**

| Model | Description |
|---|---|
| `ProcessingJob` | Extract or transcribe job, with the revision it expected |
| `ProcessingArtifact` | Checksummed audio file |
| `AsrRun` | Immutable ASR candidate; apply copies text onto the transcript |
| `AiAssistRun` | Optional cleanup or label suggestion |
| `SourceMediaCache` | Cached yt-dlp download for a source |

The source of truth for whole-segment human labels is `SegmentAnnotation`; for
in-transcript labels it is `TranscriptSpan`. `supervised_labels` and
`gold_labels` are computed at export time for segment-scope labels only. They
are not a second copy that annotators edit.

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
| GET, POST | `/api/v1/segments/<id>/annotations` | List or assign whole-segment labels. Annotators see only their rows when blind is on. | Member |
| DELETE | `/api/v1/annotations/<id>` | Soft-remove an episode | Owner, or the annotator |
| GET, POST | `/api/v1/projects/<id>/assignments` | Work queue | Member / owner |
| GET | `/api/v1/export-formats` | Format catalogue | Authenticated |
| GET | `/api/v1/projects/<id>/export` | Render a snapshot. Query: format, split, supervision, `ready_only`. | Owner |
| GET | `/api/v1/projects/<id>/quality-report` | Same document as the quality page | Owner |
| GET | `/api/v1/health` | Health check | Public |

Jobs, ASR runs, and AI assists live under `/api/v1/segments/<id>/jobs`,
`/asr/`, and `/ai/`. System default endpoints are
`/api/v1/system/asr/defaults` and `/api/v1/system/ai/defaults`.

**Spans and gold** are assigned in the segment workspace HTML
(`/projects/<id>/segments/<id>/`), not through a separate public REST surface
in this version. Exports still include `text_spans` and gold-derived
`supervised_labels` when you download a snapshot.

## Development

```
config/                 Django settings, URLs, Celery
apps/core/              Errors, auth helpers, storage port, YouTube id parse
apps/workspace/         Projects, segments, labels, spans, annotation, export, quality
  services/             Domain logic (export, agreement, gold, readiness, …)
  management/commands/  seed_admin
apps/processing/        Jobs, artifacts, ASR, AI assist, media pipeline
templates/              Bootstrap 5 pages
static/                 CSS and JavaScript
locale/                 English / Vietnamese message catalogs
docs/                   Design notes; EXAMPLE.md; software/ (SoftwareX + eval)
tests/                  pytest
```

```powershell
$env:DATABASE_URL="postgresql://youaudiolab:youaudiolab@localhost:5433/youaudiolab_django"
pytest
```

Further notes: [architecture](docs/architecture.md),
[Example walk-through](docs/EXAMPLE.md),
[SoftwareX drafts and eval](docs/software/),
[export design](docs/gate-ex1-research-dataset-export-design.md)
(historical; shipped schema is **1.2**),
[splits and supervision](docs/gate-ex3-ml-export-splits.md),
[blind and IAA](docs/gate-qc1-blind-iaa-progress.md),
[quality report](docs/gate-qc2-quality-report.md).

## Known limitations

- In-transcript labels are character spans on the accepted transcript (a word
  or a dragged phrase), not a BIO tag on every token. Agreement and gold still
  apply to the whole segment. Doccano export stays segment classification;
  span rows are in the research JSON (`text_spans`), spaCy entities, and
  `spans.csv`.
- Assigning or removing `TranscriptSpan` rows and saving gold is done in the
  workspace UI in this version; there is no separate public REST catalogue for
  those actions yet.
- YouTube description is stored when metadata is fetched. Videos imported
  before that field existed need a metadata refresh before description appears
  in the export.
- Agreement is multi-label set overlap plus per-label Cohen/Fleiss on presence,
  not Krippendorff’s alpha.
- Gold is a label set the owner saves. It is not a separate adjudication
  workflow with a conflict queue.
- YouTube download depends on yt-dlp and, for some videos, a cookies file.
  Quota and availability are outside this app.
- Celery does not reload when you edit task code. Restart the worker.
- Only PostgreSQL is supported for the constraint and race tests.

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