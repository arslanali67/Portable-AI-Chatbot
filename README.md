# PortableAI

Multi-tenant, customizable AI chatbot platform.

**Status: MVP — production-ready.** Identity + chatbot CRUD + conversations/messages + chat runtime with RAG context + streaming chat (SSE) + public embeddable widget + AI gateway (fake provider for dev/test + real OpenAI-compatible HTTP adapters, mocked in tests) + provider/model discovery + real embeddings (OpenAI-compatible, mocked in tests; fake default) + file ingestion (txt/md/pdf/docx) + URL/web ingestion (SSRF-safe) with dedup + production hardening + admin dashboard (React frontend) + Docker deployment — see `src/PROJECT_RULES.md` for the source of truth.

## Repo Layout

```text
├── src/                  # architectural source of truth (docs)
│   ├── PROJECT_RULES.md
│   └── backend/architecture.md
├── apps/
│   ├── api/              # FastAPI backend (modular monolith)
│   └── frontend/         # React + TypeScript + Vite admin dashboard
├── packages/
│   └── widget/           # public widget script (widget.js, vanilla JS, no deps)
├── infrastructure/       # deployment/infra (dev + prod docker-compose)
├── docs/                 # audit, architecture, release reports
└── tests/                # (empty) future cross-app/integration tests
```

## Prerequisites

- Python 3.11+ (existing venv: `AI chatbot`)
- Docker (for PostgreSQL + pgvector)
- No system PostgreSQL needed — dev DB runs in Docker

## 1. Activate existing virtual environment

```bash
# Windows
C:\Users\ok\Desktop\Portable AI Chatbot\AI chatbot\Scripts\activate
```

Do NOT create a new venv — one already exists at `AI chatbot`.

## 2. Install dependencies

```bash
cd apps/api
pip install -r requirements.txt
```

## 3. Configure environment

```bash
copy .env.example .env   # Windows
# edit DATABASE_URL if needed:
# DATABASE_URL=postgresql+asyncpg://portableai:portableai@localhost:5432/portableai
```

`.env` is gitignored — never commit real credentials.

## 4. Start PostgreSQL

```bash
docker compose -f infrastructure/docker-compose.yml up -d postgres
```

- Host `localhost`, port `5432` (PostgreSQL default)
- Database `portableai`, user `portableai`, password `portableai`
- Image `pgvector/pgvector:pg16` — pgvector extension available
- Persistent volume `postgres_data`

Stop: `docker compose -f infrastructure/docker-compose.yml down`

Logs: `docker compose -f infrastructure/docker-compose.yml logs postgres`

## 5. Run migrations

```bash
cd apps/api
alembic upgrade head
alembic current
alembic history
```

Migrations live in `apps/api/alembic/versions/`. Alembic sources `DATABASE_URL` from app settings (`.env`) — credentials are not in `alembic.ini`.

## 6. Start FastAPI

```bash
cd apps/api
python -m uvicorn app.main:app --reload
```

- `GET /` — service info
- `GET /api/v1/health` — health check (liveness; no DB credentials exposed)
- `GET /api/v1/ready` — readiness check (runs `SELECT 1`; 503 when DB unreachable)
- `GET /docs` — OpenAPI docs

## Production Hardening

Backend hardens for real deployments (`apps/api/app/core/`):

- **Config validation**: `ENVIRONMENT` (`development`/`test`/`production`). In `production` the app **fails fast** on weak/absent `JWT_SECRET` (< 32 chars or dev default), missing `TRUSTED_HOSTS`/`CORS_ORIGINS`, non-PostgreSQL `DATABASE_URL`, or `DEBUG=true`.
- **Trusted Hosts**: `TRUSTED_HOSTS` (JSON list of allowed `Host` headers) enforced via middleware when set.
- **Body size limit**: request bodies over `MAX_REQUEST_BYTES` (default 1 MB) → 413.
- **Centralized error handling**: unhandled exceptions become safe `{"detail": "Internal server error"}` — no stack traces, no internals; full traceback logged server-side.
- **Structured request logging**: `method path status duration_ms` middleware; bodies/headers/tokens never logged; secrets redacted in structured log payloads.
- **JWT hardening**: `decode_access_token` requires the `type: "access"` claim, so access tokens cannot be used as other token kinds.
- **Rate limiter abstraction**: routes depend on a `RateLimiter` protocol; in-memory backend today, Redis backend is a documented seam (`build_rate_limiter` factory).
- **Readiness**: `GET /api/v1/ready` performs `SELECT 1`; returns 503 with a safe payload when the DB is unreachable.

Run the hardening tests: `pytest tests/test_hardening.py`.

## Admin Dashboard (Frontend)

`apps/frontend` — React + TypeScript + Vite SPA (no state library, no UI framework). Provider/model lists are fetched from the AI management API at runtime — never hardcoded.

### Features

- **Auth**: login/register; JWT stored in `localStorage` (documented SPA trade-off; no refresh tokens). Protected routes redirect to `/login`.
- **API client**: typed DTOs mirroring the backend, automatic `Bearer` token injection, 401 → sign-out, error normalization (`detail` extraction).
- **Dashboard**: org list + chatbot counts.
- **Organizations**: list/create (name + slug).
- **Chatbot management**: list, create, edit, activate, archive, delete; provider/model selection driven by live `/api/v1/ai/*` data.
- **Knowledge**: list documents, ingest text/file/URL, delete, semantic search preview.
- **Chat console**: create/select conversations, stream SSE via `fetch` + `ReadableStream` (token-by-token rendering).
- **Widget config**: create credential with allowed origins, view embed snippet, revoke, live preview iframe reusing the real `widget.js`.
- **AI providers**: read-only provider + model metadata view.

### Run locally

```bash
cd apps/frontend
npm install          # use `npm.cmd` if `npm` is blocked by execution policy
npm run dev          # dev server on :3000, proxies /api + /widget.js to backend
npm run build        # tsc typecheck + production build → dist/
```

Vite proxies `/api` and `/widget.js` to the backend (default `http://localhost:8000`; override with `VITE_API_PROXY_TARGET`). In production the nginx container serves the SPA and proxies `/api` itself, so the API is same-origin.

## Deployment

Docker-based production stack in `infrastructure/docker-compose.prod.yml` (PostgreSQL/pgvector + API + nginx-frontend). Images build from `apps/api/Dockerfile` and `apps/frontend/Dockerfile`.

```bash
# 1. configure (fill real values; see infrastructure/.env.example)
copy infrastructure\.env.example infrastructure\.env

# 2. build + start
docker compose -f infrastructure/docker-compose.prod.yml up -d --build

# 3. run migrations (one-shot service)
docker compose -f infrastructure/docker-compose.prod.yml run --rm api-migrate
```

- nginx serves the SPA and reverse-proxies `/api/` with `proxy_buffering off` (required for SSE); healthchecks on every service; API runs as a non-root user; `.dockerignore` excludes `.env`/tests from images.
- Health: `GET /api/v1/health` (liveness), `GET /api/v1/ready` (readiness, DB check).
- Production config validation forces a strong `JWT_SECRET`, explicit `TRUSTED_HOSTS` + `CORS_ORIGINS`, and `DEBUG=false` — the API refuses to start otherwise.

## 7. Run tests

```bash
cd apps/api
pytest -m "not integration"  # fast API tests (health only; no external services)
pytest -m identity           # auth/organization/tenant-isolation tests — requires Docker PostgreSQL + alembic upgrade head
pytest -m integration        # DB foundation tests — requires Docker PostgreSQL
pytest                       # everything — requires Docker PostgreSQL + migrations applied
```

Integration tests verify session creation, `SELECT 1`, PostgreSQL reachability, and the pgvector extension.

## Identity & Auth

Multi-tenant model: `User <-- Membership --> Organization`. A user can belong to many organizations; roles are `owner`, `admin`, `member`.

### Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/register` | — | Create account (`email`, `password`, `full_name`). Duplicate email → 409. |
| POST | `/api/v1/auth/login` | — | OAuth2 form login (`username` = email, `password`). Returns `access_token`. Wrong credentials → 401. |
| GET | `/api/v1/auth/me` | Bearer | Current user profile. |
| POST | `/api/v1/organizations` | Bearer | Create organization (`name`, `slug`). Creator becomes `owner`; transactional with membership. Duplicate slug → 409. |
| GET | `/api/v1/organizations` | Bearer | Organizations the current user belongs to (tenant-isolated). |

### Dev auth flow

```bash
# register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"strong-password","full_name":"Example User"}'

# login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -d "username=user@example.com&password=strong-password"

# use token
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

### Security

- Passwords hashed with bcrypt; never stored or returned in plaintext.
- JWT access tokens (`sub` = user id, `exp`, `type`); secret from `JWT_SECRET` env var — set a strong value, never commit real secrets.
- Every organization access checks membership; JWT alone grants nothing (user is always loaded from DB).
- Generic 401 on bad credentials — no user enumeration.

## Chatbots

Organization-owned chatbot configuration. Every chatbot belongs to exactly one organization; cross-tenant access is denied at membership + role + org-scope checks.

### Endpoints (all under `/api/v1/organizations/{organization_id}/chatbots`)

| Method | Path | Role | Description |
| --- | --- | --- | --- |
| POST | `` (create) | admin+ | Create chatbot (config only; status forced to `draft`) |
| GET | `` (list) | member+ | List org's chatbots |
| GET | `/{chatbot_id}` | member+ | Get one chatbot |
| PATCH | `/{chatbot_id}` | admin+ | Partial config update (immutable: id, organization_id, timestamps) |
| POST | `/{chatbot_id}/activate` | admin+ | `draft → active` |
| POST | `/{chatbot_id}/archive` | admin+ | `draft/active → archived` |
| DELETE | `/{chatbot_id}` | admin+ | Hard delete (cascades conversations, messages, knowledge/chunks, widget config/sessions) |

- Slug unique per organization — same slug allowed in different orgs.
- Status lifecycle: `draft → active`, `draft → archived`, `active → archived`; `archived → active` → 409.
- Create payload: `name`, `slug`, `description`, `system_prompt`, `welcome_message`, `language` (`en`/`ur`), `visibility` (`private`/`public`), `provider_id`, `model_id` (defaults `fake-a` / `fake-model-small`).
- `public` visibility is required for the public widget (see Public Embeddable Widget below); `private` chatbots are never publicly accessible.

```bash
curl -X POST http://localhost:8000/api/v1/organizations/1/chatbots \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Customer Support","slug":"customer-support","description":"Support assistant","system_prompt":"You are helpful.","welcome_message":"Hello!","language":"en","visibility":"private"}'
```

## AI Gateway

Provider-agnostic gateway in `apps/api/app/ai/`. Default runtime is the deterministic offline `fake` provider (no network/key); a real OpenAI-compatible HTTP provider is implemented and enabled when `OPENAI_API_KEY` is set.

- **Contracts**: `AIRequest`, `AIResponse`, `AIMessage`, `AIUsage` — provider-neutral dataclasses; application never sees provider SDK objects.
- **ProviderRegistry** / **ModelRegistry**: extensible string ids, many models per provider, no enums, no DB migration for new models.
- **AIGateway**: validates request → resolves provider/model → checks enablement + capability → calls adapter → normalizes response/errors.
- **Capabilities**: `TEXT_GENERATION` and `STREAMING` implemented; `TOOL_CALLING`, `VISION`, etc. defined as abstraction + checks only.
- **Errors**: provider-neutral hierarchy (`AIError` → `AIProviderError` → auth/rate-limit/not-found/unavailable/`AICapabilityNotSupportedError`).
- **Providers**: `app/ai/providers/fake.py` (deterministic, offline), `base.py` (`AIProvider` protocol + `OpenAICompatibleProvider` base), `openai_compatible.py` (real HTTP adapter, mocked in tests; OpenAI/Kimi/DeepSeek/etc. all fit the same base).
- **Chatbot AI config**: each chatbot stores `provider_id` / `model_id` strings. Defaults live in `app/ai/registry.py`.

Adding a model = model metadata + registration. Adding a provider = adapter + provider metadata + models + registration. No chatbot-service, gateway, or migration changes. No API keys stored anywhere.

```python
from app.ai.registry import gateway
from app.ai.contracts import AIRequest, AIMessage, AIMessageRole

response = await gateway.generate(
    AIRequest(provider_id="fake-a", model_id="fake-model-small",
              messages=[AIMessage(AIMessageRole.USER, "hello")])
)
```

## Conversations & Messages

Persistent chat history. `Organization → Chatbot → Conversation → Message`.

### Endpoints

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/v1/organizations/{oid}/chatbots/{cid}/conversations` | Create conversation (`{"title": "..."}`); owner = current user |
| GET | `/api/v1/organizations/{oid}/chatbots/{cid}/conversations` | List conversations (`limit`/`offset`; member sees own, owner/admin see all) |
| GET | `/api/v1/organizations/{oid}/conversations/{conv_id}` | Get conversation |
| POST | `/api/v1/organizations/{oid}/conversations/{conv_id}/messages` | Create user message (`{"content": "..."}`); server assigns role `user` + sequence |
| GET | `/api/v1/organizations/{oid}/conversations/{conv_id}/messages` | List messages, `sequence_number ASC`, paginated (`limit` ≤ 200, `offset`) |
| POST | `/api/v1/organizations/{oid}/conversations/{conv_id}/archive` | `active → archived`; no restore |

- Server owns ids, roles, sequence numbers, ownership. Client sends only `title` or `content`.
- Messages are immutable — no PATCH/DELETE endpoints.
- Archived conversations stay readable but reject new messages (409).
- No conversation DELETE — archive only.
- Messages can be persisted standalone (no AI) via `POST /messages`; full assistant responses are produced by the chat endpoints (see Chat Runtime and Streaming Chat below).

```bash
# create conversation
curl -X POST http://localhost:8000/api/v1/organizations/1/chatbots/1/conversations \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"title":"Customer Support Conversation"}'

# post a user message
curl -X POST http://localhost:8000/api/v1/organizations/1/conversations/1/messages \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"content":"Hello, I need help."}'
```

## Chat Runtime

One chat turn = save user message → call AI Gateway → save assistant message.

```text
User → POST /chat → Router → ChatRuntimeService → Repositories → AIGateway → Provider (fake default; OpenAI-compatible when configured)
```

### Endpoint

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/api/v1/organizations/{oid}/conversations/{conv_id}/chat` | member+ | `{"content": "Hello"}` → 200 with `user_message` + `assistant_message` |

- Client sends only `content`; org/conversation/role/sequence/provider/model/system prompt all come from trusted server resources (`extra="forbid"`).
- History = persisted messages ordered by `sequence_number` (includes the new user message) built into a provider-neutral `AIRequest`.
- `system_prompt` comes from `Chatbot.system_prompt` — never stored as a system Message.
- `welcome_message` is preserved only; never stored as a Message.
- Transaction strategy: user message committed → gateway call outside DB transaction → assistant message committed. On AI failure the user message remains, no assistant message is created, and the conversation stays retryable. Error responses are normalized — no stack traces, keys, or provider internals.
- Archived conversation → 409 before any write or gateway call.
- Runtime context (org/chatbot/conversation/user/provider/model ids) is prepared for future telemetry; no analytics, no prompt logging.

```bash
curl -X POST http://localhost:8000/api/v1/organizations/1/conversations/1/chat \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"content":"Hello"}'
```

Future seams (not implemented): tools/agents, usage tracking, retries/fallback, per-chatbot RAG config — all against the existing `AIRequest`/`AIResponse` contracts. Streaming and RAG context assembly are implemented (see below).

## Real Provider (OpenAI-compatible)

The real provider is **Google Gemini**, integrated through the existing AI gateway via Google's OpenAI-compatible API — no gateway branching, no runtime changes.

```text
Application → AI Gateway → Provider Adapter → Gemini OpenAI-compatible API
```

- **Adapter**: `app/ai/providers/openai_compatible.py` (`OpenAICompatibleHTTPProvider`) converts `AIRequest` to the OpenAI-style payload, calls `httpx.AsyncClient` with an explicit timeout, normalizes the response, and maps HTTP errors to the provider-neutral exception hierarchy. The adapter appends `/chat/completions` to the configured base URL.
- **Provider ID / Model ID**: `gemini` / `gemini-3.6-flash` (model from `OPENAI_MODEL`).
- **Credentials**: env-only via settings (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_TIMEOUT`, `OPENAI_MODEL`). Keys are never stored in DB, chatbot, organization, metadata, JWT, logs, source, or responses.
- **Enablement**: provider/model registered as `gemini` but **disabled** unless a key is configured — no silent unauthenticated calls; clear runtime failure otherwise. Fake providers stay enabled for offline tests.
- **No retries**: one request = one provider call. Retry/backoff/fallback/circuit breaker are future seams.
- **Tests**: all real-provider tests use mocked HTTP — no network, no key required. Normal `pytest` stays offline/deterministic.

```bash
# .env (never commit a real key)
OPENAI_API_KEY=<GEMINI_API_KEY>
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
OPENAI_TIMEOUT=60.0
OPENAI_MODEL=gemini-3.6-flash
```

## Provider & Model Discovery

Read-only management APIs exposing the registries safely (authenticated).

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/ai/providers` | List providers (safe metadata only) |
| GET | `/api/v1/ai/providers/{provider_id}` | Single provider |
| GET | `/api/v1/ai/providers/{provider_id}/models` | Models for a provider |
| GET | `/api/v1/ai/providers/{provider_id}/models/{model_id}` | Single model |

```text
Client → AI Management API → AIManagementService → ProviderRegistry / ModelRegistry → Safe DTO
```

- **Credentials are never returned** — no API keys, auth headers, base URLs, or registry internals in any response.
- `enabled` reflects real state (e.g. `gemini` shows `false` without a configured key).
- Chatbot create/update validates `provider_id`/`model_id` against the registries: unknown provider/model, model from another provider, or disabled provider/model → 422.
- Read-only scope: enable/disable mutation is a future platform-admin milestone (no `platform_admin` role yet, no DB tables for providers/models).

```bash
curl http://localhost:8000/api/v1/ai/providers \
  -H "Authorization: Bearer <access_token>"
```

## Knowledge / RAG Foundation

Chatbot-owned knowledge: text ingestion → normalize → chunk → fake embeddings → pgvector storage → tenant-scoped retrieval. Wired into chat runtime and public widget chat.

```text
Document → Normalize → Chunk → Embed → pgvector → Tenant-scoped Search
```

### Endpoints (all under `/api/v1/organizations/{oid}/chatbots/{cid}/knowledge`)

| Method | Path | Description |
| --- | --- | --- |
| POST | `/documents` | Ingest text (`name`, `content`, `source_type: "text"`) → `pending → ready` |
| POST | `/documents/file` | Upload file (`multipart`: `file`, optional `title`) — txt/md/pdf/docx |
| POST | `/documents/url` | Ingest web page (`{"url": ..., "title": optional}`) — SSRF-safe |
| GET | `/documents` | List documents (safe metadata + chunk_count; no vectors) |
| GET | `/documents/{doc_id}` | Single document |
| DELETE | `/documents/{doc_id}` | Hard delete (document + chunks + vectors) |
| POST | `/search` | `{"query": "...", "top_k": 5}` → top-k `RetrievedChunk` results |

- Every query scoped by `organization_id + chatbot_id`; cross-org/cross-chatbot access returns nothing.
- Chunks: `UNIQUE(document_id, chunk_index)`, pgvector column (cosine distance, dimension 384), indexes on org/chatbot/document.
- Embeddings: `fake` (deterministic, offline, default) or `openai` (real HTTP, mocked in tests, enabled with key). Dimension validation enforced (mismatch → error).
- Document status lifecycle server-owned: `pending → processing → ready`, failure `processing → failed`.
- Failed ingestion never leaves `ready` without valid chunks/vectors.
- File ingestion: `.txt`, `.md`, `.pdf`, `.docx` only; memory processing, extension + size (10 MB) + extracted-text (100k chars) limits; malformed files → safe 422.
- Deduplication: SHA-256 hash of normalized content; same org + chatbot + content → 409; different chatbot/org → allowed. Client cannot set hash/status/vectors (`extra="forbid"`).
- URL ingestion: public pages only; SSRF protection (scheme/port/credentials rejected, hostname resolved and every IP checked against loopback/private/link-local/metadata ranges, redirects re-validated, max 5); timeout 15s; response cap 5 MB; `text/html`/`application/xhtml+xml` only; HTML extracted (scripts/styles/tags stripped) then runs the same normalize→chunk→embed pipeline; robots.txt respected (404 = no restriction, other failures fail closed); canonical URL stored in `source_uri`.

### RAG in Chat Runtime

Chat runtime retrieves knowledge and assembles context **above** the AI Gateway (`ContextBuilder`); the gateway stays provider-agnostic.

```text
User → Chat → ChatRuntime → RetrievalService → ContextBuilder → AIRequest → AIGateway → Assistant
```

- Flow: authorize → save user message → retrieve (server-side org + chatbot, latest user content) → ContextBuilder → gateway once → save assistant message.
- `chatbot.system_prompt` is always authoritative; retrieved text is delimited reference data (`<knowledge_context>` user message), never replaces the prompt.
- Client cannot inject `top_k`/RAG config/provider/model/system prompt (`extra="forbid"`).
- Empty retrieval = normal generation (no fake context). Retrieval failure = user message stays, no AI call, no assistant, safe 500.
- RAG context is never persisted as a Message row.
- Limits: `rag_top_k` (5), `rag_max_context_chars` (8000) — centralized config.
- Tenant/chatbot isolation: retrieval scoped to the conversation's own org + chatbot; cross-org/cross-chatbot knowledge never reaches the AI request (tested).

### Streaming Chat (SSE)

`POST /api/v1/organizations/{oid}/conversations/{conv_id}/chat/stream` — same request body and authorization rules as normal chat.

```text
user message → authz → persist user → history → retrieval → ContextBuilder
→ AIGateway.stream → SSE token events → assemble → persist ONE assistant message
```

- SSE events: `start`, `user`, `token` (multiple), `end` (carries persisted message id + sequence), `error` (safe generic detail).
- Reuses the same RAG pipeline and ContextBuilder as normal chat; provider streaming is normalized through `AIStreamEvent` (never raw provider chunks).
- Fake provider streams deterministically offline; OpenAI-compatible provider streams via `httpx` (mocked in tests).
- Only the final assistant response is persisted as one Message; token chunks are never stored.
- On mid-stream failure: user message stays, no assistant message, `error` event emitted; no secrets/stack traces/raw payloads in events.
- Normal `POST /chat` unchanged.

```bash
curl -N -X POST http://localhost:8000/api/v1/organizations/1/conversations/1/chat/stream \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"content":"Hello"}'
```

## Public Embeddable Widget

Embed a chatbot on any website with a single script tag. Anonymous visitors get a floating chat UI backed by the same ChatRuntime / RAG / SSE pipeline.

```html
<script src="http://localhost:8000/widget.js" data-chatbot="PUBLIC_KEY" async></script>
```

### Setup (admin)

1. Create + activate a chatbot, set `visibility: "public"`.
2. Create a public credential (admin+):

```bash
curl -X POST http://localhost:8000/api/v1/organizations/{oid}/chatbots/{cid}/widget-config \
  -H "Authorization: Bearer <access_token>" \
  -d '{"allowed_origins": ["https://yoursite.com"]}'
# → {"public_key": "...", "enabled": true}
```

- `allowed_origins` optional; empty list = any origin (dev). Non-empty = exact origin allow-list enforced server-side (403 otherwise). No "allow everything" default.
- `GET /{chatbot_id}/widget-config` and `DELETE /{chatbot_id}/widget-config` (revoke) also exist.

### Public API (no JWT)

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/v1/public/widget/session` | `{"public_key", "origin"}` → `session_token` + safe config (`chatbot_name`, `welcome_message`, `language`, `enabled`) |
| POST | `/api/v1/public/widget/chat/stream` | `{"session_token", "content", "origin"}` → SSE events `user`, `start`, `token`*, `end` / `error` |

- Public identity = per-chatbot `public_key` (cryptographically random, non-sequential, safe to expose, revocable). Client never supplies org/chatbot/user/provider/model/system prompt/top_k — the server derives everything from the public key + session (`extra="forbid"`).
- Anonymous sessions: random unguessable `session_token`, bound to exactly one chatbot, expire after `widget_session_ttl_hours` (24). No fake User accounts per visitor — one inactive placeholder user per organization owns widget conversations.
- One conversation per session; both the user message and the final assistant message are persisted; token chunks are never stored. Failed stream = no assistant message.
- RAG: the widget uses the existing RetrievalService + ContextBuilder; retrieved knowledge reaches the model, scoped to the chatbot's own org (cross-tenant knowledge never crosses, tested).
- Rate limiting (MVP in-memory backend behind a `RateLimiter` protocol — Redis-backed backend is a documented seam): per-session 30 msgs/hr, per-IP 1000/hr → 429. Session/chat payloads capped (`content` ≤ 20000 chars).
- Errors: invalid/revoked key, inactive/private chatbot → 404 (no enumeration); origin denied → 403; invalid/expired session → 403/error event; invalid content/fields → 422; rate limited → 429; runtime/provider failure → safe generic error, never secrets.
- `widget.js` is served by the API (`GET /widget.js`), vanilla JS with no dependencies: floating launcher, chat panel, SSE streaming render, session persistence in `localStorage`, plain-text rendering (XSS-safe `textContent`, no `innerHTML` with model output), duplicate-initialization guard, async-load safe.
- The authenticated org APIs are unchanged — JWT still required there.

## Rules

See `src/PROJECT_RULES.md` and `src/backend/architecture.md`. New features are defined in `src/` before code.
