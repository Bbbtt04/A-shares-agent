# Railway Deployment

This repository is prepared for a two-service Railway project.

## Current deployment

- Project: `A-shares-agent`
- API service: `https://api-production-aabb.up.railway.app`
- Web service: `https://web-production-d6ea7.up.railway.app`

## CLI deployment flow

The current machine needs a Railway login before deployment:

```powershell
npx --yes @railway/cli login
```

After login, create one project with two services:

```powershell
npx --yes @railway/cli init --name A-shares-agent
npx --yes @railway/cli add --service api
npx --yes @railway/cli add --service web
```

Generate public domains for both services:

```powershell
npx --yes @railway/cli domain --service api
npx --yes @railway/cli domain --service web
```

Set variables before deploying the web service so Vite bakes in the API URL:

```powershell
npx --yes @railway/cli variable set VITE_API_BASE_URL=https://<api-service-domain> --service web
npx --yes @railway/cli variable set API_PROXY_URL=https://<api-service-domain> --service web
npx --yes @railway/cli variable set CORS_ORIGINS=https://<web-service-domain> --service api
```

Deploy both services:

```powershell
npx --yes @railway/cli up . --service api --detach
npx --yes @railway/cli up .\web --path-as-root --service web --detach
```

## API service

- Root directory: repository root
- Builder: Dockerfile
- Public health check: `/api/health`
- Start command is defined by the root `Dockerfile`.

Useful Railway variables:

```text
PORT=<Railway sets this automatically>
CORS_ORIGINS=https://<web-service-domain>
```

When running on Railway without `CORS_ORIGIN_REGEX` configured, the API also accepts
Railway public domains matching `https://*.up.railway.app` so the first deployment can
work before a custom domain is attached. Set `CORS_ORIGINS` and `CORS_ORIGIN_REGEX`
explicitly if you want a tighter production policy.

## Web service

- Root directory: `web`
- Builder: Dockerfile
- Public health check: `/`
- Static files are served by Caddy from the Vite `dist` output.

Set this Railway variable on the web service:

```text
VITE_API_BASE_URL=https://<api-service-domain>
API_PROXY_URL=https://<api-service-domain>
```

If `VITE_API_BASE_URL` is empty, the frontend uses same-origin `/api/...`, which is
still useful for local Vite development with the existing dev proxy and for the
Railway Caddy reverse proxy.
