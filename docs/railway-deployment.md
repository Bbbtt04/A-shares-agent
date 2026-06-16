# Railway Deployment

This repository is prepared for a two-service Railway project.

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
```

If `VITE_API_BASE_URL` is empty, the frontend uses same-origin `/api/...`, which is
still useful for local Vite development with the existing dev proxy.
