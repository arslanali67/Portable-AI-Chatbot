# PortableAI — Render Deployment

Deploys the existing project on Render as three resources:

| Resource | Render type | Directory |
| --- | --- | --- |
| `portableai-api` | Web Service (Python) | `apps/api` |
| `portableai-frontend` | Static Site | `apps/frontend` |
| `portableai` | PostgreSQL (managed, pgvector supported) | — |

A Blueprint (`render.yaml` at the repo root) defines all three. No application
code, database schema, or API contracts are changed for deployment; the project
is deployed as-is.

## 1. Prerequisites

- Push this repository to GitHub/GitLab and link it to Render.
- Create a new Blueprint from the `render.yaml` in the repo root.

## 2. Fill the prompted environment variables

The Blueprint marks secrets/URLs with `sync: false` so they are never stored in
the repo. Fill them in the Render Dashboard after provisioning:

### Backend (`portableai-api`)

| Variable | Required | Value |
| --- | --- | --- |
| `ENVIRONMENT` | set automatically | `production` (activates fail-fast config validation) |
| `JWT_SECRET` | auto-generated | leave the generated value (≥ 32 chars) |
| `DATABASE_URL` | **yes** | Render Postgres internal connection string converted to asyncpg, see below |
| `CORS_ORIGINS` | **yes** | JSON array of the frontend origin(s), e.g. `["https://portableai-frontend.onrender.com"]` |
| `TRUSTED_HOSTS` | **yes** | JSON array of the backend host(s), e.g. `["portableai-api.onrender.com"]` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | optional | `30` |
| `LOG_LEVEL` | optional | `INFO` |
| `OPENAI_API_KEY` | optional | leave empty to keep the built-in fake provider |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | optional | only if using a non-default OpenAI-compatible endpoint |
| `EMBEDDING_PROVIDER_ID` | optional | `fake` (default, offline) or `openai` |
| `OPENAI_EMBEDDING_MODEL` | optional | only if embeddings are `openai` |

**DATABASE_URL format.** The app requires the asyncpg driver and validates the
URL in production. Copy Render's *Internal Database URL* and convert it:

```text
postgres://USER:PASSWORD@HOST:PORT/portableai?sslmode=require
↓
postgresql+asyncpg://USER:PASSWORD@HOST:PORT/portableai?ssl=require
```

Two changes: scheme `postgres://` → `postgresql+asyncpg://`, and query
`?sslmode=require` → `?ssl=require` (asyncpg's SSL parameter). The `vector`
extension is enabled by the first Alembic migration and is supported by Render
Postgres.

### Frontend (`portableai-frontend`)

| Variable | Required | Value |
| --- | --- | --- |
| `VITE_API_BASE_URL` | **yes** | the backend Web Service URL, e.g. `https://portableai-api.onrender.com` |

`VITE_API_BASE_URL` is baked into the production bundle at build time. Without
it the frontend keeps its existing relative-path behavior (dev proxy /
same-origin). The widget embed snippet shown in the admin also uses this value
so it points at the backend's `/widget.js`.

## 3. Commands used by Render

- Backend build: `pip install -r requirements.txt` (from `apps/api`)
- Backend pre-deploy (migrations, runs before traffic): `alembic upgrade head`
- Backend start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
- Backend health check: `GET /api/v1/ready` (returns 200 when PostgreSQL is
  reachable, 503 otherwise)
- Frontend build: `npm ci && npm run build` (from `apps/frontend`)
- Frontend publish directory: `apps/frontend/dist`
- SPA fallback: rewrite `/*` → `/index.html` (client-side routing)

## 4. Local development is unchanged

- Backend: `python -m uvicorn app.main:app --reload` from `apps/api`
- Frontend: `npm run dev` (Vite dev server on :3000 proxies `/api` and
  `/widget.js` to `http://localhost:8000`)
- No `VITE_API_BASE_URL` needed locally — leave it unset.

## 5. Notes / manual steps

- Migration runs only via `preDeployCommand`; if a deploy is blocked on
  migration you can also run `alembic upgrade head` with a one-off shell.
- The Blueprint uses the `free` plan; switch to a paid plan (and enable always-on)
  before serving real traffic. Free services spin down when idle.
- No Redis is required: the MVP ships the in-memory rate limiter.
- Render does not rotate the generated `JWT_SECRET`; treat it as a platform secret.