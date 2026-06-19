# Deployment Overview

This document explains how the project should be deployed and which runtime
pieces own frontend, backend, storage, scheduled jobs, and future database
migration.

## Target Shape

The production system has four runtime concerns:

```text
Browser
  -> Web Console
  -> Backend API
  -> Persistent application data
  -> Scheduled daily jobs
```

Recommended services:

| Service | Runtime | Source path | Responsibility |
| --- | --- | --- | --- |
| `web` | Caddy serving a Vite build | `web/` | Static React console and `/api/*` reverse proxy |
| `api` | Uvicorn/FastAPI | repository root | Console API, reports, strategy data, job triggers |
| `scheduler` | Python command or platform cron | repository root | Daily recommendation and settlement jobs |
| `storage` | SQLite files, JSONL files, local Qdrant files | `/app/data`, `/app/reports` | Strategy ledger, events, traces, reports, RAG index |

In the current codebase, the database and RAG index are file-backed. That is
simple and good for an MVP, but it makes shared writes across multiple services
the main deployment constraint.

## Current Storage Model

The API reads and writes these paths relative to the repository root inside the
container:

| Path | Used for | Production handling |
| --- | --- | --- |
| `data/daily_strategy.sqlite` | Structured strategy ledger | Must persist |
| `data/knowledge.sqlite` | Lightweight knowledge store | Should persist |
| `data/qdrant/` | Local Qdrant vector index | Must persist if RAG is enabled |
| `data/config/llm_runtime.json` | LLM provider and route config | Must persist; contains secrets |
| `data/events/` | JSONL event stream | Should persist |
| `data/traces/` | Decision traces | Should persist |
| `data/metrics/` | Runtime metrics | Should persist |
| `data/audit/` | Audit records | Should persist |
| `data/runtime/checkpoints/` | Agent checkpoints | Should persist |
| `data/strategy_learning/` | One-pick learning state | Should persist |
| `data/premarket_learning/` | Premarket factor learning state | Should persist |
| `reports/premarket/` | Premarket report JSON/Markdown | Must persist |
| `reports/daily/` | Daily review reports | Should persist |

For a Docker platform, mount persistent volumes to:

```text
/app/data
/app/reports
```

## Frontend Deployment

The frontend is a Vite app built by `web/Dockerfile` and served by Caddy.

Runtime options:

1. Same-origin API access:
   - Leave `VITE_API_BASE_URL` empty.
   - Set `API_PROXY_URL` to the backend service URL.
   - Browser calls `/api/...` on the web domain.
   - Caddy forwards `/api/*` to the API.

2. Direct API access:
   - Set `VITE_API_BASE_URL=https://<api-domain>`.
   - Browser calls the API domain directly.
   - API must set `CORS_ORIGINS=https://<web-domain>`.

The recommended production default is same-origin API access through Caddy. It
reduces browser CORS surface and lets users open only the web domain.

## Backend Deployment

The backend is built by the root `Dockerfile`.

The container starts:

```bash
uvicorn trading_agent_system.api.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

Required runtime configuration:

| Variable | Required | Notes |
| --- | --- | --- |
| `PORT` | Platform-provided | Railway injects this automatically |
| `CORS_ORIGINS` | Recommended | Web domain when direct API access is used |
| `CORS_ORIGIN_REGEX` | Optional | Tighten or widen allowed origins |
| `PYTHONIOENCODING` | Recommended | Already set to `utf-8` in Dockerfile |
| `RUN_JOB_TIMEOUT_SECONDS` | Optional | Fallback timeout for API-triggered jobs, default `60` |
| `PREMARKET_JOB_TIMEOUT_SECONDS` | Optional | Premarket agent timeout override, default `300` |

Health check:

```text
GET /api/health
```

## Scheduler Deployment

The scheduler entry point is:

```text
scripts/daily_premarket_scheduler.py
```

It reads and writes the same `data/` and `reports/` paths as the API:

```bash
python scripts/daily_premarket_scheduler.py \
  --recommendation-time 08:45 \
  --settlement-time 09:31 \
  --db-path data/daily_strategy.sqlite \
  --report-dir reports/premarket \
  --event-dir data/events \
  --learning-dir data/premarket_learning \
  --top-n 10
```

With the current SQLite/local-Qdrant storage model, do not deploy a separate
scheduler service unless it can read and write the same persistent data as the
API. If the platform gives each service a separate volume, the scheduler and API
will drift.

Safe deployment choices:

1. MVP: run API and use manual or API-triggered jobs.
2. Single-writer container: run scheduler alongside API only if one volume is
   shared by both processes in the same service.
3. Production scale: move strategy data to PostgreSQL and Qdrant to a dedicated
   service, then run scheduler as a separate service or platform cron.

## Database Decision

Keep SQLite for the first Railway deployment if:

- There is one API instance.
- Scheduled jobs are not writing from a separate service with its own isolated
  volume.
- The goal is MVP validation and a small private console.

Move to PostgreSQL when:

- API and scheduler need to run as separate services.
- More than one backend replica may write strategy data.
- You need managed backups, migrations, or SQL inspection outside the container.
- You want Railway plugins or external managed database operations.

Current code has no PostgreSQL adapter or migration layer, so PostgreSQL is a
separate implementation step. The deployment docs should treat SQLite as the
current supported database.

## RAG Decision

Current RAG uses local Qdrant file mode through `data/qdrant/`.

Keep local Qdrant for MVP if:

- The API is a single instance.
- RAG writes happen in the same persistent data directory.
- You can back up `data/qdrant/` with the rest of `data/`.

Move to a dedicated Qdrant service when:

- Multiple services or replicas need to read/write RAG data.
- Re-indexing becomes slow or operationally important.
- You replace deterministic embeddings with real embedding models.

## CI/CD Model

Use GitHub Actions as the deployment gate and Railway as the deployment engine:

```text
pull request -> GitHub Actions checks
merge to main -> GitHub Actions checks on main
Railway waits for CI -> Railway autodeploys api and web
```

This keeps deployment credentials out of GitHub Actions. Railway handles the
actual deployment after it sees a successful commit on `main`.

If a future workflow must deploy from GitHub Actions directly, use a Railway
project token stored as `RAILWAY_TOKEN`, but that is not the recommended first
path for this project.

## Release Checklist

Before merging to `main`:

```bash
python -m pytest -q
cd web
npm ci
npm run build
```

After deployment:

```bash
curl https://<api-domain>/api/health
curl https://<web-domain>/api/health
```

Also verify:

- Web console loads.
- `/api/health` returns `status: ok`.
- `data/` and `reports/` are mounted to persistent storage.
- `data/daily_strategy.sqlite` exists after the first strategy run.
- `reports/premarket/` contains the latest premarket report after a run.
- LLM config is set through runtime configuration, not committed to Git.
