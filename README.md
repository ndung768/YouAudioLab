# YouAudioLab

YouAudioLab is an open-source platform for building **reproducible YouTube-derived
audio–text datasets** while retaining **source-video metadata** and **processing
provenance**. A researcher registers a YouTube source, defines time-bounded
segments, extracts checksummed WAV artifacts, and optionally drafts a transcript
with ASR. Human annotators label each segment; the owner can hide peer labels,
measure agreement, curate a gold set, and export a snapshot that keeps the same
video out of both train and test.

The design target is an auditable corpus object: known source bytes and
metadata, known cuts, revision-checked artifacts, known annotators, and a
source-video split. Version 0.1.0 does **not** extract visual features or ship a
self-contained video dataset; retained video IDs, descriptions, and
source-relative timestamps support later audiovisual linkage where the original
video can lawfully be accessed.

## Live demo

A hosted workspace is at **[https://youaudiolab.duthu.net/](https://youaudiolab.duthu.net/)**.

| Field | Value |
|---|---|
| Login identifier | `hoangduy0610` |
| Password | `Duy@06102004` |

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Getting started](#getting-started)
- [Example](#example)
- [Illustrative evaluation](#illustrative-evaluation)
- [Building a corpus](#building-a-corpus)
- [Export formats](#export-formats)
- [Data model](#data-model)
- [API reference](#api-reference)
- [Development](#development)
- [Known limitations](#known-limitations)
- [License and data](#license-and-data)

## What it does

- **YouTube-native workflow.** Import a URL, store video metadata, define
  segments, extract audio, review ASR/AI suggestions, annotate, and export in
  one environment.
- **Revision-aware artifact provenance.** Each extract job stores
  `expected_revision`. If bounds change from interval A to B while extraction A
  is still running, `definition_revision` increments and `current_artifact` is
  cleared; the old job is marked stale and cannot publish the A cut as current.
  The segment has no current WAV until a successful extract for B. Verified
  artifacts keep a SHA-256 checksum.
- **Annotation and dataset provenance.** Per-annotator labels, accepted
  transcripts, owner-curated gold, supervision policy, and source-video split
  travel with the export. ASR and AI outputs stay candidates until a person
  applies them.
- Annotators work one segment at a time: listen, read the transcript, label the
  whole clip, or select a phrase and label that text. Blind mode shows only
  their own episodes and spans.
- Work queue (assign, start, complete, release) supports overlap for agreement.
  Progress reports Jaccard, Cohen’s κ, and Fleiss’ κ; Quality covers duration
  buckets and per-video coverage.
- Exports include verified WAVs in the dataset zip. Splits are by source video
  (default seed 42, ratios 0.8 / 0.1 / 0.1), not by random segment.

ASR and AI keys stay on the account or system settings and are encrypted at
rest. Project settings only choose which provider and model to inherit.

## Architecture

<img src="docs/software/figures/figure1-architecture.png" alt="YouAudioLab architecture: presentation, Django application, data, and processing layers" width="560" />

*Figure 1. Overall architecture of YouAudioLab.*

Six layers: browser (projects, segment workspace with player/transcript/labels,
members, export), Django pages and REST API over domain services, PostgreSQL,
file store for source cache and checksummed WAVs, Redis as Celery broker only,
and workers (yt-dlp, FFmpeg, on-server or OpenAI ASR, optional Ollama on the same
host). Pages and the API share the same membership checks. Slow work — metadata,
audio extract, transcription — runs in Celery. A job stores the segment
revision it was started against. If the bounds change before publish, the job
becomes stale and does not replace the current artifact.

<img src="docs/software/figures/Figure%202.%20Four-phase%20workflow%20of%20YouAudioLab%20-%20revision-checked%20extraction%20transcription%20review%20annotation%20and%20audio-inclusive%20dataset%20export.png" alt="Four-phase workflow of YouAudioLab: revision-checked extraction, transcription review, annotation, and audio-inclusive dataset export" width="640" />

*Figure 2. Four-phase workflow of YouAudioLab: revision-checked extraction, transcription review, annotation, and audio-inclusive dataset export.*

| Component | Choice |
|---|---|
| Framework | Django 6.1, Django REST Framework 3.18 |
| Database | PostgreSQL 16 |
| Task queue | Celery with a Redis broker |
| Media | yt-dlp + FFmpeg |
| Speech draft | On-server Whisper-style ASR (`local`), or OpenAI. Annotators do not install a model. |
| Assist | Ollama on the YouAudioLab host, optional and separate from ASR |
| Frontend | Bootstrap 5 and vanilla JavaScript |
| Languages | English and Vietnamese |
| Local ports | HTTP **8001**, Postgres **5433**, Redis **6381** |

## Getting started

**Docker Compose (recommended full stack).** `docker compose up --build` runs the
application image (`python:3.12.14-slim` + FFmpeg and app dependencies) together
with fixed tags `postgres:16.10` and `redis:7.4-alpine` on the ports above. See
`docs/software/eval/ENVIRONMENT.md` for the evaluation environment record. That
image does not reload when you edit source.

**Native development.** Install Python 3.12–3.14 and FFmpeg on `PATH`. Use Docker
only for the bundled Postgres and Redis (or point `DATABASE_URL` / Redis URLs at
your own services):

```powershell
cd YouAudioLab
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
| `ASR_ENGINE` | On-server engine (`fake` in `.env.example`; use `faster-whisper` when installed on the YouAudioLab host). Not the annotator’s computer. |
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
Default seed login is `admin` / `demo@123`. Change that password on any
install you control. The [live demo](https://youaudiolab.duthu.net/) uses a
separate hosted account (`hoangduy0610`).
The same seeded user is Django `AUTH_USER_MODEL` (`workspace.AppUser`) with
`is_staff` / `is_superuser`, so it can also open **<http://localhost:8001/admin/>**.
The app is at **<http://localhost:8001/identity/>**. Health:
**<http://localhost:8001/api/v1/health>**.

Use `runserver` (and a local Celery worker) while developing; use Compose
`--build` when you want the packaged stack without a host Python/FFmpeg install.

## Example

A full walk-through of one YouTube cut—protocol, extract, ASR apply, dual
annotation with optional text spans, and a `by_source` export—is in
**[docs/EXAMPLE.md](docs/EXAMPLE.md)** (with UI screenshots).

Figures and the evaluation protocol live under
**[docs/software/](docs/software/)**.

## Illustrative evaluation

Version 0.1.0 reports **three** checks that share one pilot sample but use
different procedures and (where noted) different models. Logs and the
environment record are under [docs/software/eval/](docs/software/eval/). Confirm
the figures there before quoting them; this section is a summary.

The shared sample is **60 segments** (21.67 min of audio; mean duration 21.7 s)
from **19 YouTube videos** of Northern Vietnamese drama dialogue (*Về nhà đi
con*). Metadata and timestamps are in
[docs/software/eval/sample_segments.csv](docs/software/eval/sample_segments.csv)
(seed 42). The original MP3/WAV clips are not redistributed; figures that
depend on those bytes are reproducible only against a local copy of the same
clips.

### Software validation

![Integrity and consistency verification workflow of YouAudioLab](docs/software/figures/Figure%203.%20Integrity%20and%20consistency%20verification%20workflow%20of%20YouAudioLab.png)

*Figure 3. Integrity and consistency verification workflow of YouAudioLab.*

Machine timing used pre-extracted local MP3 clips and faster-whisper `base`
(Vietnamese, CPU, INT8). The 2.37 min total is summed worker wall-clock for
MP3-to-16 kHz mono WAV conversion (0.10 min) plus that recogniser (2.27 min).
Live YouTube retrieval, queue waiting, and human review sit outside the sum.
Host pins for that run: Windows 11, YouAudioLab 0.1.0, Python 3.12.14,
FFmpeg 7.1.1 ([docs/software/eval/ENVIRONMENT.md](docs/software/eval/ENVIRONMENT.md)).

Each row names where that figure was measured. Timing, checksum, and the
FFmpeg repeat use the 60 clips. Stale publication, blind labelling, the
source-video split, and export provenance are automated tests on PostgreSQL
and fixtures.

| Check | Where it was measured | Result |
|---|---|---|
| Worker time, extract + ASR | 60 local clips, faster-whisper `base` | 2.37 min; 120/120 jobs succeeded; 0 retries; 0 failed |
| Artifact checksum | 60 published WAVs from those clips | 60/60 matched the stored SHA-256 |
| FFmpeg repeat, 3 runs | Same 60 clips, one environment | 60/60 identical SHA-256 |
| Stale publication | 100 sequential revision-change trials, plus a PostgreSQL row-lock race | 0 stale files published. This is a transactional check, not a multi-worker load test |
| Blind labelling | Automated PostgreSQL test | 0 overwrites; annotator rows kept after gold assignment |
| Source-video split | Automated export test, seed 42 | 0 videos shared across splits |
| Export provenance | Automated export test | JSON and ZIP kept source, revision, checksum, transcript, annotations, gold, and split; ZIP WAV checksums matched the stored artifacts |

### Exploratory human–AI session

![Workflow for comparing manual and AI-assisted audio annotation in YouAudioLab](docs/software/figures/Figure%204.%20Workflow%20for%20comparing%20manual%20and%20AI-assisted%20audio%20annotation%20in%20YouAudioLab.png)

*Figure 4. Workflow for comparing manual and AI-assisted audio annotation in YouAudioLab.*

**Separate models from the timing run above:** this session uses
PhoWhisper-small for transcription drafts and OpenAI `gpt-5.6-luna` for
whole-segment label suggestions. One annotator first transcribed and labelled
the same 60 segments by hand. On the second pass the segment order was changed,
the first pass was hidden, and the annotator reviewed those suggestions. The
manual label set is that person’s first pass, used as the reference for this
comparison. It is a single-annotator reference on this sample.

Cohen’s κ treats each whole-segment label set as one nominal category.
Transcript comparison counts words after lowercasing, punctuation removal, and
whitespace normalisation. Insertions and deletions were not counted separately,
so the word figure is an overlap rate. The label inventory and class balance
are not part of this summary. With chance agreement pₑ = 0.2194, κ sits above
the raw match rate because agreement expected by chance on these set-categories
is low.

| Metric | Result |
|---|---|
| Exact label-set matches | 52 / 60 (0.8667) |
| Cohen’s κ | 0.8292 (pₑ = 0.2194) |
| Exact transcript matches | 31 / 60 (0.5167) |
| Word overlap | 2,934 / 3,047 reference words (0.9629), with 113 substitutions reported |
| Session time | 9,953 s on the manual pass; 4,905 s on the later AI-assisted pass |

Exact label sets matched on 52 segments and exact transcripts on 31, so
segment-level transcript review still matters on this sample. The same person
heard the same audio twice, manual pass first. The 5,048 s gap (50.72% of the
manual pass; speedup factor **2.03**) describes that order of work; it is an
exploratory observation, not a causal estimate of AI benefit.

Download the exported pilot package for this comparison:
[Speech Emotion-dataset_zip.zip](docs/software/eval/manually_assited_comparison/Speech%20Emotion-dataset_zip.zip)
(companion CSVs and the evaluation workbook are in the same
[manually_assited_comparison](docs/software/eval/manually_assited_comparison/)
folder).

### Comparative workflow vs Label Studio

A single-operator stopwatch comparison used the same 19 videos and 60
pre-defined segment bounds. Source selection and start/end times were given in
advance so the timed gap is **active preparation**, not content selection.
Figures describe these two workflows only—not a general usability or
performance benchmark across all Label Studio setups.

| Stage | Label Studio-based workflow (evaluated) | YouAudioLab |
|---|---|---|
| Active source / audio preparation | External tools; ~**180 s** / video | Integrated URL registration; ~**15 s** / video |
| Segment bounds | Manual; comparable effort | Integrated; comparable effort |
| Extract + annotation-task creation | External cut / import | Automatic after bounds |
| ASR / LLM suggestions | Custom ML backend | Integrated ASR / LLM |
| Human review (60 segments) | 55 min 02 s | 53 min 18 s (Δ 104 s) |

The main efficiency difference was preparation and handoff (~91.7% less active
user time at that stage in this comparison). Review time was similar.
Equivalent provenance can be built beside Label Studio; YouAudioLab keeps
source metadata, segment revisions, processing records, and SHA-256 checks in
the processing path itself.

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
docs/                   Design notes; EXAMPLE.md; software/ (figures + eval)
tests/                  pytest
```

```powershell
$env:DATABASE_URL="postgresql://youaudiolab:youaudiolab@localhost:5433/youaudiolab_django"
pytest
```

Further notes: [architecture](docs/architecture.md),
[Example walk-through](docs/EXAMPLE.md),
[figures and eval](docs/software/),
[export design](docs/gate-ex1-research-dataset-export-design.md)
(historical; shipped schema is **1.2**),
[splits and supervision](docs/gate-ex3-ml-export-splits.md),
[blind and IAA](docs/gate-qc1-blind-iaa-progress.md),
[quality report](docs/gate-qc2-quality-report.md).

## Known limitations

- Retained video metadata is **not** synchronized frames or precomputed visual
  features.
- Machine timing and FFmpeg repeatability used **pre-extracted local MP3s**, not
  live YouTube retrieval; live-retrieval reproducibility is not claimed.
- Artifact-level reproducibility is within one environment and configuration;
  cross-platform bitwise identity is not claimed.
- `content_hash` fingerprints a concrete DB snapshot (entity IDs and row
  timestamps included), not a UUID-free semantic dataset identity.
- Checksums assert integrity at verification time; they do not by themselves
  prevent later silent overwrite of stored files.
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
- Gold is a label set the owner saves (owner-curated reference, not independent
  ground truth). It is not a separate adjudication workflow with a conflict
  queue.
- Source-video splitting reduces shared-video leakage; it does not guarantee
  speaker-disjoint folds when the same speaker appears in more than one video.
- Human–AI and Label Studio timing results are single-operator / single-annotator
  exploratory observations (order and familiarity effects possible).
- YouTube download depends on yt-dlp and, for some videos, a cookies file.
  Quota and availability are outside this app.
- Celery does not reload when you edit task code. Restart the worker.
- Only PostgreSQL is supported for the constraint and race tests.

## License and data

Source repository: [https://github.com/ndung768/YouAudioLab](https://github.com/ndung768/YouAudioLab)

Release:
[v0.1.0](https://github.com/ndung768/YouAudioLab/releases/tag/v0.1.0)

Archival DOI:
[https://doi.org/10.5281/zenodo.23752831](https://doi.org/10.5281/zenodo.23752831)

The software is licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).

**A software licence does not cover the recordings you collect.** Audio and
transcripts taken from YouTube remain subject to YouTube’s terms and to the
speakers’ rights. In Vietnam, personal data in a corpus is also subject to
Decree 13/2023/ND-CP. Record the licence you intend to publish under, and the
consent you actually have, in project settings. Those fields are written into
the snapshot and the quality report so a later reader can see them next to the
files.

Maintained by Quoc-Dung Nguyen · nguyenquocdung@pyu.edu.vn