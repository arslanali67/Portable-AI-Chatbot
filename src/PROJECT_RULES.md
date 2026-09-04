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
- Auth via short-lived access JWTs backed by DB-tracked, single-use rotating refresh tokens (httpOnly cookie; theft detected via reuse, revoking the whole token family).
- Tenant isolation is enforced at the data layer, not only the API layer.
- Secrets live in environment variables, never in code or committed files.

## 7. AI Gateway / RAG Abstraction

AI capabilities are **implemented**: a provider-agnostic AI gateway (`app/ai/`), RAG/knowledge ingestion and retrieval (`app/rag/`, `app/services/retrieval.py`, `app/services/context_builder.py`), real OpenAI-compatible providers and embeddings (env-configured, mocked in tests), SSE streaming, and the public embeddable widget. The platform defines clean seams for future extensions:

- `services/agents/` (future): agent orchestration on top of the gateway + RAG.
- Future extensions: credential management/BYOK, more providers, advanced retrieval (hybrid search, reranking, semantic cache), background workers.
- Chatbot models/schemas never leak provider-specific concepts; the chatbot entity stays provider-agnostic and provider/model selection is runtime config.

## 8. Current Scope — MVP (Complete)

In scope:
- FastAPI application skeleton, `/` and `/api/v1/health` endpoints
- Config, security, logging, dependency wiring
- Centralized async database foundation (SQLAlchemy 2.x + PostgreSQL + pgvector + Alembic)
- Multi-tenant identity system: users, organizations, memberships, email+password auth, JWT access tokens; a separate, non-tenant-scoped `users.is_platform_admin` flag for platform-level administration, orthogonal to organization membership/roles
- Session hardening: rotating refresh tokens (httpOnly cookie, DB-tracked, reuse-detection) shortening the access-token XSS window; self-service password reset (DB-backed single-use token, generic enumeration-safe responses, resets revoke all refresh-token sessions). Email delivery is real, via Resend (`RESEND_API_KEY`, `settings.email_from_address`, direct HTTP call — no SDK dependency); local dev/test without a configured key falls back to logging the reset URL instead of sending — see architecture.md's Refresh Token Rotation & Password Reset section.
- Chatbot CRUD + configuration, tenant-scoped, with lifecycle (draft/active/archived) and role permissions
- Provider-agnostic AI gateway foundation: contracts, registries, capabilities, fake providers, error hierarchy (no real provider calls)
- Conversation + message storage (persistent chat history), tenant-scoped, immutable messages
- Chat runtime: one turn = save user message, call AI Gateway, save assistant message
- Real provider integration: OpenAI-compatible HTTP adapter (credentials from env, mocked in tests); fake providers stay default for offline tests
- Provider & model management: discovery APIs over the registries; safe DTOs, no credential exposure, chatbot provider/model validation; platform-admin-gated enable/disable mutation via a thin DB override table (registries remain the sole source of executable adapter definitions, capabilities, and credentials — the DB never stores them)
- BYOK (bring-your-own-key): organization-scoped, Fernet-encrypted AI provider API keys in `ai_provider_credentials`, optional per (organization, provider), falls back to the platform-shared key when absent, never re-displayed after entry (masked last-4 indicator only), orthogonal to the existing enable/disable override.
- Structured output: per-chatbot JSON-schema-validated responses via `chatbots.response_schema` (nullable — NULL keeps today's free-text behavior unchanged), gated by the existing per-model `AICapability.STRUCTURED_OUTPUT` check; the platform validates the model's output against the schema server-side (never trusting the provider's own json-mode guarantee), retries once with the validation error fed back to the model as corrective feedback, and rejects clearly with no persistence if the retry is still invalid.
- Tool calling with platform-defined execution: per-chatbot tool selection via `chatbots.tools` (a list of `{"name", ...}` entries, validated against a small code-owned registry — `app/ai/tools/` — at save time; unknown names are rejected), optional (NULL/empty = today's behavior unchanged), gated by the existing per-model `AICapability.TOOL_CALLING` check. When the model requests a registered tool, the platform executes it in-process (never an organization-defined or webhook-style tool, never arbitrary chatbot-defined endpoints — that decision stands permanently) and feeds the result back to the model, looping up to a small bounded number of iterations before forcing a final tools-omitted answer. Only the turn's final assistant response is persisted (one turn = one persisted assistant message, matching the existing pattern for multi-call turns); a full tool-execution audit trail (name, arguments, result per call) rides in that message's metadata. Mutually exclusive with `response_schema` for now — a chatbot with both configured keeps tool calls surface-only and unexecuted, matching pre-milestone behavior; combining the two is a distinct future refinement.
- RAG/knowledge foundation: text ingestion → normalize → chunk → embeddings → pgvector storage → tenant-scoped retrieval
- Hybrid search: `RetrievalService`/`ChunkRepository` combine pgvector cosine similarity with Postgres full-text search (`tsvector`/GIN) via Reciprocal Rank Fusion (RRF); no new external dependency, `search()`'s signature unchanged, composes transparently with per-chatbot `rag_enabled`/`rag_top_k`.
- RAG runtime integration: ChatRuntime retrieves knowledge via RetrievalService and assembles context via ContextBuilder (above AIGateway); system prompt authoritative. Per-chatbot RAG config (`chatbots.rag_enabled`, `chatbots.rag_top_k`) lets each chatbot enable/disable retrieval and override `top_k`; `rag_enabled=false` skips RetrievalService entirely (not called-and-discarded), and `rag_top_k=NULL` falls back to the global `settings.rag_top_k` default, which remains the platform default.
- Real embeddings (OpenAI-compatible, mocked in tests) + file ingestion (txt/md/pdf/docx) with deduplication; fake embeddings stay default for offline tests
- URL/web ingestion: SSRF-safe fetch (DNS/IP checks, validated redirects), HTML extraction, reuses shared pipeline; public pages only, robots.txt respected
- Bounded same-domain crawl ingestion: `POST .../knowledge/documents/crawl` (new endpoint, distinct from single-URL ingestion) takes an entry URL, fetches it via the existing SSRF-safe `SecureHTTPFetcher`/`URLValidator`, discovers same-registrable-domain links from the already-fetched HTML (no sitemap.xml parsing; registrable-domain matching via `tldextract` — `www.example.com`/`blog.example.com` both match an `example.com` entry, `example.co.uk` does not, distinct `*.github.io` sites are correctly treated as different domains), and ingests up to `max_crawl_pages` (default 50) pages — each through the exact same fetch/extract/chunk/embed pipeline as single-URL ingestion, one `KnowledgeDocument` per page, committed per-page so partial results survive an early stop — bounded by a hard same-registrable-domain-only rule (never a genuinely different domain than the entry URL, non-negotiable), a max crawl depth of 3 (entry page = depth 0), and a wall-clock crawl budget (default 120s) that ends the crawl early with whatever's been ingested so far rather than exceed it. `robots.txt` is fetched and cached once per crawl (per domain), not once per page — single-URL ingestion keeps its existing per-call check unchanged. Synchronous — blocks until the capped crawl finishes and returns the created documents plus a summary (pages fetched/ingested/skipped/failed, stop reason); no background job/polling, since the caps keep total time within the production reverse proxy's read/send timeout (raised to accommodate the crawl budget with headroom). Rate-limited to 5 crawls/hour per organization via the existing `RateLimiter` factory.
- Streaming chat (SSE): normalized AIStreamEvent contract, provider-agnostic AIGateway.stream, fake + OpenAI providers stream, one persisted assistant message
- Public embeddable widget: public_key identity, anonymous sessions, origin control, rate limiting, widget.js package, reuses existing runtime/RAG/SSE
- Widget customization: per-widget theme (`theme_color`, `widget_position`, `avatar_url` on `widget_configs`, NULL = current built-in default; avatar is an uploaded image served from local disk, not a freeform admin-entered URL) and functional per-chatbot widget language (existing `chatbot.language`, now actually consumed by `widget.js` instead of fetched-and-ignored, including RTL layout for `ur`); new lightweight public config endpoint and `WidgetConfig` update path; no change to `widget_sessions`, authentication, or the existing public-response allowlist discipline
- Preset/FAQ questions: `chatbots.preset_questions` (nullable JSON, `list[{"question", "answer"}]`, max 10 entries, question ≤200 chars, answer ≤2000 chars) — admin-authored canned Q&A, mirroring `chatbots.tools`'s "bounded list of small dicts, edited as a whole, validated at save time, reject clearly don't silently accept" precedent. Exposed eagerly (both question and answer) on the existing public widget config response — non-secret, admin wants visitors to see them. Ships on **both** the public widget and the authenticated admin test console. Clicking a suggested question is a canned-response click, never an AI Gateway call: `POST /api/v1/public/widget/faq` (`{session_token, question_index}`, rate-limited like `chat/stream`) and `POST /api/v1/organizations/{organization_id}/conversations/{conversation_id}/faq` (`{question_index}`, same membership auth as a normal chat turn) both look up the pair server-side by index (never trusting client-supplied text) via one shared persistence method, and persist it as an ordinary USER+ASSISTANT message pair — real conversation history, so a follow-up chat message has full context — but each UI renders the answer instantly client-side without waiting on that round-trip.
- Production hardening: environment detection + fail-fast config validation, CORS/trusted hosts from env, centralized safe error handling, request body limits, readiness check separate from liveness, structured logging (no secrets), rate-limiter backend abstraction with a Redis-backed implementation (fixed-window INCR+EXPIRE, fail-open on Redis unavailability; in-memory stays the dev/test default), auth/JWT review, authorization audit
- Frontend admin dashboard (`apps/frontend`, React + TypeScript + Vite): auth (login/register/logout), organization dashboard, chatbot management, knowledge management, chat test console (SSE streaming), widget configuration + embed snippet + live preview, provider/model read-only visibility
- Deployment: backend + frontend Dockerfiles, production docker-compose (PostgreSQL + API + frontend reverse proxy), environment documentation, `.env.example` with safe placeholders
- Transient AI-provider error retry: `AIGateway.generate`/`.stream` automatically retry the same request (never a different provider/model, never a circuit-breaker halt) up to 3 total attempts with short exponential backoff, only for `AIProviderUnavailableError`-class failures (503/504/408/timeout). Streaming retries only while zero content tokens have been sent for that turn; once any token has streamed, the retry window closes and failures propagate exactly as before. 429 (rate limit) and all other error classes are never retried. Exhausting all attempts falls through to the existing `RuntimeErrorAI(502, "AI provider unavailable")` — this reduces how often that's reached, not the failure UX itself. Logically still one chat turn, one persisted assistant message, regardless of how many provider HTTP calls the retry made internally.
- Platform-owner dashboard: read-only cross-organization visibility for `is_platform_admin` users only, via `GET /api/v1/platform/organizations` (list) and `GET /api/v1/platform/organizations/{id}` (detail) — the first and only deliberate cross-tenant read surface in this codebase, everything else remains strictly `organization_id`-scoped. Exposes only aggregate/metadata signals (name, slug, owner email, member/chatbot counts, last-activity timestamp, member/chatbot lists) — never message or conversation content, never `system_prompt`, never credential material. Includes a reversible disable/enable toggle (`organizations.disabled_at`/`disabled_message`, both nullable) via `POST /api/v1/platform/organizations/{id}/disable` and `.../enable`: disabling immediately blocks that organization's admin-console access (`require_organization_role`/`require_organization_membership` 403 on the very next request) and its public widget (config and chat/stream endpoints show the configured `disabled_message` or a generic fallback, never proceeding to a session/response); enabling clears both fields and restores access immediately. No separate session-invalidation logic — enforcement re-checks the organization row on every request.
- Billing (Stripe, flat tiers): per-organization subscription lifecycle via Stripe Checkout + webhook-driven sync, in a new `subscriptions` table (`organization_id` unique, `tier`, `status`, `stripe_customer_id`, `stripe_subscription_id`, `current_period_end`) — no row means Free tier, always active, never touched by billing logic (existing organizations are unaffected on deploy). Tiers (Free/Pro/Enterprise) are code-owned metadata (`app/billing/tiers.py`) mapping to Stripe Price IDs from settings, never hardcoded pricing. The platform-wide Stripe secret key is stored Fernet-encrypted in a new single-row `stripe_credential` table (reusing the existing `settings.ai_credential_encryption_key`, no second encryption key), admin-settable via a new platform dashboard settings page, mirroring BYOK's masked/write-only pattern; the webhook signing secret (`STRIPE_WEBHOOK_SECRET`) stays a deployment-fixed environment variable, not DB-stored. `POST /api/v1/billing/webhook` is signature-verified before any parsing and lives entirely outside normal JWT auth (Stripe cannot send a JWT). A canceled/lapsed subscription (`customer.subscription.updated`/`.deleted`) reuses the existing platform-dashboard disable mechanism (`organizations.disabled_at`/`disabled_message`) rather than a parallel concept; recovery to `active` re-enables the same way. `invoice.payment_failed` is synced/logged only — never an immediate disable — deferring to Stripe's own retry/dunning window, only the eventual `canceled` status acts. A platform admin can also directly set an organization's tier/status from the dashboard (`PATCH /api/v1/platform/organizations/{id}/subscription`), bypassing Stripe entirely (e.g. to comp an account) — a later real webhook event overwrites this via the same upsert, no special-casing. A self-serve invoice-history page queries Stripe live (`stripe.Invoice.list`) — no locally-synced invoice table. Tests run against a mocked Stripe client — no real Stripe account or network call anywhere.

Explicitly out of scope (do not implement yet):
- OAuth (Google/GitHub login), email verification, MFA (password reset and refresh tokens are now in scope, including real transactional email delivery via Resend — see the session-hardening bullet above)
- More real providers (Anthropic, Kimi, DeepSeek, etc.) (platform-shared credentials remain environment/platform controlled; BYOK is a per-organization override on top, not a replacement)
- WebSocket transport, idempotency keys, fallback (switching provider/model on failure), circuit breaker (halting all calls to a provider after repeated failures) — transient-failure retry-with-backoff is implemented; see architecture.md's AI Gateway Architecture section
- Reranking (deferred separately — needs an explicit decision between local model inference and an external rerank API/service before implementation), semantic cache, document versioning, sitemap.xml parsing, JS-rendered page crawling, OCR, background workers (bounded same-registrable-domain crawl ingestion is now in scope — see above; unbounded/deep crawling and background-job-based crawling remain out)
- Public widget analytics
- API keys in DB, full DB-backed provider/model CRUD (registries remain the code-owned source of truth for adapter definitions, capabilities, and credentials — only an admin-controlled enable/disable override is DB-backed)
- LangChain, LlamaIndex
- Integrations, analytics
