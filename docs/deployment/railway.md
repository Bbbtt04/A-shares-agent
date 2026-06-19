# Railway Deployment Guide

This guide describes the recommended Railway deployment for the current project
state. It assumes GitHub is the source of truth and Railway autodeploys from the
`main` branch after GitHub Actions succeeds.

## Service Layout

Create one Railway project with two services first:

| Service | Root directory | Build config | Health check | Domain |
| --- | --- | --- | --- | --- |
| `api` | `/` | `railway.json` + root `Dockerfile` | `/api/health` | public |
| `web` | `/web` | `web/railway.json` + `web/Dockerfile` | `/` | public |

Do not add `scheduler` as a separate service until storage is shared through
PostgreSQL or another shared backend. With the current SQLite file database,
separate Railway services can easily write to separate volumes and show
different state.

## Initial CLI Setup

From the repository root:

```powershell
npx --yes @railway/cli login
npx --yes @railway/cli init --name A-shares-agent
npx --yes @railway/cli add --service api
npx --yes @railway/cli add --service web
```

Create public domains:

```powershell
npx --yes @railway/cli domain --service api
npx --yes @railway/cli domain --service web
```

## Service Settings

In the Railway dashboard, configure both services from the GitHub repository:

```text
Repository: Bbbtt04/A-shares-agent
Branch: main
Autodeploy: enabled
Wait for CI: enabled
```

Set service roots:

```text
api root: /
web root: /web
```

The repository already contains:

```text
railway.json
web/railway.json
Dockerfile
web/Dockerfile
web/Caddyfile
```

## Environment Variables

Recommended web variables:

```text
API_PROXY_URL=https://<api-domain>
```

Leave `VITE_API_BASE_URL` unset for the first deployment. The frontend will call
same-origin `/api/...`, and Caddy will proxy to `API_PROXY_URL`.

Recommended API variables:

```text
CORS_ORIGINS=https://<web-domain>
```

The API also accepts Railway `*.up.railway.app` origins when
`RAILWAY_ENVIRONMENT` is present and `CORS_ORIGIN_REGEX` is unset. Set explicit
CORS values once the final domains are known.

Optional API variables:

```text
CORS_ORIGIN_REGEX=
PYTHONIOENCODING=utf-8
```

`PYTHONIOENCODING` is already set by the Dockerfile.

## Persistent Volumes

Attach persistent storage to the `api` service for:

```text
/app/data
/app/reports
```

Required persisted data:

```text
/app/data/daily_strategy.sqlite
/app/data/config/llm_runtime.json
/app/data/qdrant/
/app/data/events/
/app/data/traces/
/app/data/metrics/
/app/data/audit/
/app/reports/premarket/
/app/reports/daily/
```

If the platform does not support two mounted paths on one service, use one
volume at `/app/data` and treat reports as rebuildable until a second persistent
path or object storage is introduced. Strategy state must take priority over
report files.

## Deploy Manually

Manual deploy remains useful for the first release:

```powershell
npx --yes @railway/cli up . --service api --detach
npx --yes @railway/cli up .\web --path-as-root --service web --detach
```

After this is working, rely on GitHub autodeploy from `main`.

## GitHub CI/CD

This repository uses GitHub Actions for checks only:

```text
.github/workflows/ci.yml
```

Recommended flow:

1. Open a PR.
2. GitHub Actions runs backend tests and frontend build.
3. Merge to `main`.
4. GitHub Actions runs again on `main`.
5. Railway waits for CI and autodeploys `api` and `web`.

This avoids storing Railway deploy tokens in GitHub.

## Scheduler Options

Current scheduler command:

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

Do not run this as a separate Railway service while SQLite is the primary
database unless the scheduler and API read/write the same data. Safer staged
plan:

1. Launch `api` and `web`.
2. Run recommendation/settlement manually or through API-triggered jobs.
3. Add backups for `/app/data/daily_strategy.sqlite`.
4. Migrate strategy ledger to PostgreSQL.
5. Add `scheduler` as a separate service or Railway cron.

## Database Roadmap

Phase 1, current supported deployment:

```text
SQLite file: /app/data/daily_strategy.sqlite
RAG index: /app/data/qdrant/
```

Phase 2, production hardening:

```text
PostgreSQL: strategy ledger and daily job state
Dedicated Qdrant: vector index
Object storage or persistent volume: reports
```

Do not enable multiple backend replicas before the SQLite write path is replaced
or carefully constrained to a single writer.

## Verification

After deployment:

```powershell
curl https://<api-domain>/api/health
curl https://<web-domain>/api/health
```

Expected API response includes:

```json
{
  "status": "ok"
}
```

Check from the web console:

- The app loads without blank screen.
- API-backed panels load.
- Daily strategy page handles empty state cleanly.
- Running a job writes data under `/app/data` and reports under `/app/reports`.

## Rollback

Code rollback:

1. Roll Railway service back to the previous deployment.
2. Keep volumes mounted.
3. Re-check `/api/health`.

Data rollback:

1. Stop writes.
2. Back up the current SQLite file.
3. Restore the last known-good `daily_strategy.sqlite`.
4. Restart the API service.
5. Verify `/api/daily-strategy/latest`.
