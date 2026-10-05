# Evaluation / reproduction environment

This file records the host and container image tags used for the SoftwareX
software-validation pilot and for the recommended Docker Compose stack. Prefer
these fixed tags over floating `:latest` / unpinned major tags when reproducing.
Image digests are not claimed here unless recorded separately.

## Host machine (pilot reported in the manuscript)

| Item | Value |
| --- | --- |
| OS | Windows 11 Home Single Language (registry may still report ProductName as Windows 10; OS build 26200 = Windows 11 25H2) |
| Display version | 25H2 |
| Build | 26200.9457 (`NT 10.0.26200`) |
| Python | 3.12.14 |
| FFmpeg | 7.1.1 (essentials_build) |
| faster-whisper | 1.2.1 |
| CTranslate2 | 4.8.2 |
| yt-dlp | 2026.8.19 |
| Django | 6.1.1 |
| Django REST Framework | 3.18.1 |
| Celery | 5.6.3 |
| Docker Engine (host tooling) | 28.5.1 |
| Docker Compose | v2.40.2-desktop.1 |

Python dependencies for the application are also locked in the repository root
`uv.lock` (install with `uv sync` or `pip install -e ".[dev]"` from the tagged release).

## Docker Compose version-pinned images (`docker-compose.yml`)

| Service | Image tag |
| --- | --- |
| `db` | `postgres:16.10` |
| `redis` | `redis:7.4-alpine` |
| `web` / `worker` | built from `Dockerfile` (`FROM python:3.12.14-slim`, installs FFmpeg via apt, then `pip install ".[dev]"`) |

Reproduce the stack:

```bash
docker compose up --build
```

Reproduce software-invariant tests (requires Compose Postgres reachable at `DATABASE_URL`):

```bash
uv run pytest tests/test_jobs_races.py tests/test_asr_stale.py tests/test_i3_export_provenance.py -q
```

## Archival record

The GitHub release tag `v0.1.0` archives source, Compose/Dockerfile pins, `uv.lock`,
`docs/software/eval/` scripts, CSV logs, and redistributable fixtures. A Zenodo DOI
deposit of the same tree is recommended for a second permanent landing page; until
deposited, treat the GitHub release as the archival reproducibility package.
