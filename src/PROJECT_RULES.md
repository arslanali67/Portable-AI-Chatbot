# PortableAI — Project Rules

PortableAI is a multi-tenant, customizable AI chatbot platform. This document is the **architectural source of truth** for the project.

## 1. Source of Truth

- `src/` is the architectural source of truth.
- Before any feature is implemented, it must first be defined in architecture documents under `src/`.
- If a new feature is added:
  1. Define it in `src/`
  2. Then implement code
- No duplicate implementations. Shared logic lives in exactly one place.

## 2. Architecture Principles

- **Clean architecture**: layers are `api` -> `services` -> `repositories` -> `models`. Dependencies point inward; no layer imports upward.
- **Modular monolith**: backend ships as one deployable application with clear internal module boundaries.
- **Multi-tenancy is mandatory**: every resource belongs to an organization. All queries and writes are scoped by tenant.
- **API versioning**: all endpoints live under `/api/v1/`. Future versions use `/api/v2/`, etc.

## 3. Technology Stack

| Layer | Choice |
| --- | --- |
| API framework | FastAPI |
| ORM | SQLAlchemy 2.x (async, typed/declarative) |
| Database | PostgreSQL (dev via Docker) |
| Vector search | pgvector (extension enabled; `document_chunks.vector`, dimension 384) |
| Async DB driver | asyncpg |
| Cache / async queue | Redis |
| Migrations | Alembic (owns all schema changes) |
| Auth tokens | PyJWT (JWTs) |
| Password hashing | bcrypt (direct; passlib incompatible with bcrypt 5.x) |
| Settings | pydantic-settings |

## 3a. Database Rules

- One central async engine and one central session factory in `app/core/database.py`.
- Repositories/services/routes never create engines; sessions come via `get_db()` dependency injection.
- No engine per request.
- Schema changes only through Alembic migrations; app code never creates/alters tables.
- `DATABASE_URL` comes from environment/`.env`; credentials never hardcoded in code or `alembic.ini`.
- pgvector extension enabled by migration; vector operations go through the `EmbeddingProvider` abstraction (`app/rag/`), so business logic never touches vector SQL directly.
- Schema stays multi-tenant ready (tenant-scoped tables carry `organization_id`; scoping enforced at repository layer).

## 4. Backend Layout

```text
apps/api/
├── app/
│   ├── main.py            # FastAPI app entry point
│   ├── core/              # config, database, security, dependencies, logging
│   ├── api/v1/            # versioned routers
│   ├── models/            # SQLAlchemy ORM models
│   ├── schemas/           # Pydantic request/response schemas
│   ├── repositories/      # data access layer
│   └── services/          # business logic layer
├── tests/                 # backend unit/integration tests
├── alembic/               # migration environment
├── requirements.txt
└── alembic.ini
```

## 5. Multi-Tenancy

- Tenant = organization. Every table (except global reference tables) carries an `organization_id`.
- Repository layer always scopes queries by `organization_id`.
- Tenant context is resolved from the authenticated request (JWT claim) and propagated via FastAPI dependencies.

## 6. Security

- Passwords hashed with bcrypt; never stored in plaintext.
- Auth via short-lived access JWTs (refresh tokens are out of scope).
- Tenant isolation is enforced at the data layer, not only the API layer.
- Secrets live in environment variables, never in code or committed files.

## 7. AI Gateway / RAG Abstraction

AI capabilities are **implemented**: a provider-agnostic AI gateway (`app/ai/`), RAG/knowledge ingestion and retrieval (`app/rag/`, `app/services/retrieval.py`, `app/services/context_builder.py`), real OpenAI-compatible providers and embeddings (env-configured, mocked in tests), SSE streaming, and the public embeddable widget. The platform defines clean seams for future extensions:

- `services/agents/` (future): agent orchestration on top of the gateway + RAG.
- Future extensions: tool calling, structured output, credential management/BYOK, more providers, advanced retrieval (hybrid search, reranking, semantic cache), background workers.
- Chatbot models/schemas never leak provider-specific concepts; the chatbot entity stays provider-agnostic and provider/model selection is runtime config.

## 8. Current Scope — MVP (Complete)

In scope:
- FastAPI application skeleton, `/` and `/api/v1/health` endpoints
- Config, security, logging, dependency wiring
- Centralized async database foundation (SQLAlchemy 2.x + PostgreSQL + pgvector + Alembic)
- Multi-tenant identity system: users, organizations, memberships, email+password auth, JWT access tokens; a separate, non-tenant-scoped `users.is_platform_admin` flag for platform-level administration, orthogonal to organization membership/roles
- Chatbot CRUD + configuration, tenant-scoped, with lifecycle (draft/active/archived) and role permissions
- Provider-agnostic AI gateway foundation: contracts, registries, capabilities, fake providers, error hierarchy (no real provider calls)
- Conversation + message storage (persistent chat history), tenant-scoped, immutable messages
- Chat runtime: one turn = save user message, call AI Gateway, save assistant message
- Real provider integration: OpenAI-compatible HTTP adapter (credentials from env, mocked in tests); fake providers stay default for offline tests
- Provider & model management: discovery APIs over the registries; safe DTOs, no credential exposure, chatbot provider/model validation; platform-admin-gated enable/disable mutation via a thin DB override table (registries remain the sole source of executable adapter definitions, capabilities, and credentials — the DB never stores them)
- RAG/knowledge foundation: text ingestion → normalize → chunk → embeddings → pgvector storage → tenant-scoped retrieval
- RAG runtime integration: ChatRuntime retrieves knowledge via RetrievalService and assembles context via ContextBuilder (above AIGateway); system prompt authoritative
- Real embeddings (OpenAI-compatible, mocked in tests) + file ingestion (txt/md/pdf/docx) with deduplication; fake embeddings stay default for offline tests
- URL/web ingestion: SSRF-safe fetch (DNS/IP checks, validated redirects), HTML extraction, reuses shared pipeline; public pages only, robots.txt respected
- Streaming chat (SSE): normalized AIStreamEvent contract, provider-agnostic AIGateway.stream, fake + OpenAI providers stream, one persisted assistant message
- Public embeddable widget: public_key identity, anonymous sessions, origin control, rate limiting, widget.js package, reuses existing runtime/RAG/SSE
- Production hardening: environment detection + fail-fast config validation, CORS/trusted hosts from env, centralized safe error handling, request body limits, readiness check separate from liveness, structured logging (no secrets), rate-limiter backend abstraction (in-memory MVP, Redis seam), auth/JWT review, authorization audit
- Frontend admin dashboard (`apps/frontend`, React + TypeScript + Vite): auth (login/register/logout), organization dashboard, chatbot management, knowledge management, chat test console (SSE streaming), widget configuration + embed snippet + live preview, provider/model read-only visibility
- Deployment: backend + frontend Dockerfiles, production docker-compose (PostgreSQL + API + frontend reverse proxy), environment documentation, `.env.example` with safe placeholders

Explicitly out of scope (do not implement yet):
- OAuth (Google/GitHub login), password reset, email verification, MFA, refresh tokens
- More real providers (Anthropic, Kimi, DeepSeek, etc.), credential management, BYOK, credential management UI (credentials remain environment/platform controlled)
- WebSocket transport, idempotency keys, retries/fallback/circuit breaker
- Reranking, hybrid search, semantic cache, document versioning, recursive crawling/sitemaps/JS rendering/OCR, per-chatbot RAG config, background workers
- Widget customization UI beyond the current public config (themes/languages per-install), public widget analytics
- API keys in DB, full DB-backed provider/model CRUD (registries remain the code-owned source of truth for adapter definitions, capabilities, and credentials — only an admin-controlled enable/disable override is DB-backed)
- Redis usage (rate limiter is in-memory MVP; Redis-backed backend is a documented seam)
- LangChain, LlamaIndex
- Integrations, billing, analytics
