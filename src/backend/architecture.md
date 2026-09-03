# PortableAI Backend — Architecture

Status: **MVP + production foundation**. Backend, AI gateway, RAG, streaming, public widget, production hardening, and admin dashboard all implemented. See roadmap in §32.

## 1. Overview

PortableAI backend is a **modular monolith** built on **FastAPI**. It serves multi-tenant, customizable AI chatbots. The MVP provides the application skeleton, health endpoints, configuration, a centralized async database foundation (PostgreSQL + pgvector + SQLAlchemy 2.x + Alembic), identity/auth, chatbot management, the AI gateway, real provider/embedding adapters, RAG/knowledge ingestion and retrieval, SSE streaming, the public widget, and production hardening.

## 2. Architectural Style

### Modular Monolith

- One deployable application (`apps/api`).
- Internal modules with explicit boundaries: `core`, `api`, `models`, `schemas`, `repositories`, `services`.
- Modules can later be extracted into microservices (e.g., AI gateway) without rewriting the domain layer.

### Clean Architecture

Dependency rule — dependencies point inward, never outward:

```text
api (routers) -> services -> repositories -> models
                        ^
                        |---- schemas (boundary DTOs)
```

- **Routers**: HTTP concern only. Parse requests, call services, build responses.
- **Services**: business logic, orchestration, invariants. No HTTP/SQL knowledge.
- **Repositories**: data access. Single place that touches ORM/SQL. Enforce tenant scoping.
- **Models**: SQLAlchemy ORM entities.
- **Schemas**: Pydantic DTOs — request/response contracts, never the ORM models themselves.

## 3. Tech Stack

| Concern | Technology | Notes |
| --- | --- | --- |
| API | FastAPI | async-ready, OpenAPI out of the box |
| Server | uvicorn | ASGI, `uvicorn[standard]` |
| ORM | SQLAlchemy 2.x | async, typed/declarative style |
| Async DB driver | asyncpg | `postgresql+asyncpg://` |
| DB | PostgreSQL | primary datastore, dev via Docker |
| Vector search | pgvector | extension enabled; `document_chunks.vector` (dimension 384) |
| Migrations | Alembic | schema versioning, single source of schema truth |
| Cache/queue | Redis | future: sessions, rate limits, job queues |
| Settings | pydantic-settings | env-driven config, `DATABASE_URL` from env |
| Validation | Pydantic v2 | schemas |
| Auth tokens | PyJWT | JWT access tokens |
| Hashing | bcrypt (direct) | passwords; passlib avoided (incompatible with bcrypt 5.x) |
| HTTP client | httpx | used by OpenAI-compatible provider/embedding adapters and URL ingestion |

## 4. Request Flow

```text
HTTP client
   -> uvicorn
   -> FastAPI app (main.py)
   -> /api/v1 router (api/v1/router.py)
   -> endpoint handler
   -> service (business logic)
   -> repository (data access, tenant-scoped)
   -> SQLAlchemy (async ORM)
   -> PostgreSQL
```

## 5. Database Architecture

### PostgreSQL

PostgreSQL is the primary relational database. Development instance runs in Docker (`infrastructure/docker-compose.yml`, `pgvector/pgvector` image) so every developer gets an identical environment with pgvector available. Production deployment is defined in `infrastructure/docker-compose.prod.yml` (PostgreSQL + API + frontend nginx).

### pgvector

pgvector is a PostgreSQL extension that supports embeddings and vector search. The extension is enabled by the first Alembic migration (`CREATE EXTENSION IF NOT EXISTS vector`). The `document_chunks.vector` column (dimension 384, centralized in config) stores embeddings, and `ChunkRepository.search` performs tenant-scoped cosine search. Vector operations go through the `EmbeddingProvider` abstraction (`app/rag/embeddings.py`); business logic never touches pgvector implementation details directly.

### SQLAlchemy 2.x

SQLAlchemy 2.x is the ORM/data-access foundation, in modern typed/declarative style (`Mapped[...]` / `mapped_column(...)`). Database access is **async** (`create_async_engine`, `async_sessionmaker`, `AsyncSession`), matching FastAPI's async request handling. One central engine and one central session factory live in `core/database.py`.

### One Central Engine, One Central Session Factory

- `core/database.py` owns the single `engine` and `AsyncSessionLocal` factory.
- Repositories receive sessions by injection — they never create engines.
- Services and routers never create engines.
- No engine is ever created per request; the engine is created once at import and reused.
- Testing swaps the session factory or engine, never the architecture.

### Alembic

Alembic owns the database schema. Application code never creates or alters tables manually — every schema change is a migration under `apps/api/alembic/versions/`. `env.py` reads `DATABASE_URL` from application settings (`app.core.config.settings`) and targets `Base.metadata` so future models are discovered automatically. Credentials are never hardcoded in `alembic.ini`, `env.py`, or migration files.

### Configuration

Database credentials come from environment/configuration only — `.env` in development, environment variables in any other environment. `DATABASE_URL` is required; the app refuses to start without it. Secrets are never hardcoded in Python.

### Multi-Tenant

The schema is multi-tenant: tenant = organization, tenant-scoped tables carry `organization_id`, and repositories enforce scoping at the data layer (`TimestampMixin` in `models/base.py` gives every table audit columns).

### Vector Abstraction

Business logic does not couple to pgvector specifics. A vector/embedding service layer (`app/rag/embeddings.py`, `app/services/retrieval.py`) wraps pgvector operations; application code talks to that abstraction, not to raw vector SQL.

## 6. Database Session Lifecycle

```text
request -> get_db() dependency -> AsyncSession (scoped to request)
        -> handler/repository work inside session
        -> dependency teardown closes session
```

- `get_db()` in `core/database.py` is the only way handlers obtain a session.
- Sessions are short-lived, request-scoped, created per request and closed on teardown (`async with` / `finally`).
- Repositories receive the session via constructor injection.
- Transaction boundaries live in the service layer (`async with session.begin()` or explicit commit), keeping repositories transactional-primitive-only.
- Connection pooling is handled by the single engine; sessions are cheap, connections are reused.

## 7. Migration Policy

- All schema changes go through Alembic migrations. Hand-editing tables is forbidden.
- Migrations are committed with the code that introduces the schema change.
- `alembic upgrade head` applies pending migrations; `alembic downgrade` rolls back where practical (the pgvector enable migration is reversible).
- Autogenerate (`alembic revision --autogenerate`) is used as a draft; every migration is reviewed before commit.
- No credentials in `alembic.ini` — `env.py` sources `DATABASE_URL` from application settings.

## 8. Multi-Tenancy

- Tenant = **organization**.
- Identity model: `User <-- Membership --> Organization` (many-to-many via `memberships` join table).
- Every tenant-scoped table has `organization_id`.
- Repositories scope every query/write by `organization_id` — enforcement at data layer.
- Authorization checks membership for every organization access; knowing an `organization_id` never grants access by itself.
- Current tenant is derived from the authenticated user's memberships — not from a JWT claim.

## 8a. Platform-Owner Cross-Organization Dashboard

The one deliberate exception to this section's tenant-isolation invariant: `GET /api/v1/platform/organizations` and `GET /api/v1/platform/organizations/{id}`, gated by `require_platform_admin()` (§15), grant a platform admin read access to every organization's metadata — something no other code path in this system does. Scope of the exception is narrow and explicit:

- **Exposed** — list: `id`, `name`, `slug`, `created_at`, `owner_email` (derived from the `owner`-role membership), `member_count`, `chatbot_count`, `last_activity_at` (derived from `MAX(conversations.updated_at)`, nullable — no new usage-tracking infrastructure). Detail adds: member list (`email`, `role`, `joined_at`), chatbot list (`name`, `slug`, `status`, `created_at`), aggregate `message_count`.
- **Never exposed** — message/conversation content, `system_prompt`, any BYOK credential material, tool-execution trace content.
- `PlatformService` owns these queries, reading repositories/models directly for cross-org aggregates. It never calls into any existing service method that assumes single-org scoping — those services' trust boundary is unchanged by this feature's existence.

### Disable / Enable

- `organizations.disabled_at` (nullable timestamp) and `organizations.disabled_message` (nullable text, admin-configurable) — reversible, not one-way: `POST /api/v1/platform/organizations/{id}/disable` sets `disabled_at` (+ optional `disabled_message`); `POST .../enable` clears both back to `NULL`. Both `Depends(require_platform_admin)`.
- **Admin-console enforcement**: `require_organization_role(...)` and `require_organization_membership` (`app/core/dependencies.py`) — the two dependencies every org-scoped route already funnels through — additionally 403 with a clear, generic message ("This organization has been disabled") when `organization.disabled_at IS NOT NULL`. Since both dependencies already re-fetch the `Organization` row on every call, this blocks an already-open session on its very next request — no separate session-invalidation mechanism needed.
- **Public widget enforcement**: `app/api/v1/public_widget.py`'s org resolution path (`public_key → chatbot → organization`) checks `disabled_at` at both the config endpoint and the chat/stream endpoint (a visitor can hit either independently) — if disabled, responds with the organization's `disabled_message` if set, otherwise a generic fallback ("This assistant is currently unavailable."), and never proceeds to session creation or chat/stream.
- Enabling restores all access immediately, at both the admin-console and public-widget paths — no residual disabled state anywhere once `disabled_at` is cleared.

## 8b. Billing (Stripe, Flat Tiers)

Per-organization flat-tier subscriptions via Stripe Checkout, synced by webhook. Mocked Stripe client in every test — no real Stripe account or network call anywhere in this codebase.

### Data Model

- `subscriptions` (`app/models/subscription.py`): `organization_id` (FK, UNIQUE — one subscription per organization), `tier` (nullable str), `status` (nullable str, Stripe's own vocabulary: `active`/`past_due`/`canceled`/`incomplete`/`unpaid`/etc.), `stripe_customer_id` (nullable), `stripe_subscription_id` (nullable), `current_period_end` (nullable timestamptz), timestamps.
- **No row for an organization means Free tier, always active, never touched by any billing logic.** A row is created only when an organization's owner starts a real Checkout flow, or a platform admin manually assigns a tier. This migration creates zero rows for existing organizations — deploying this feature cannot disable or otherwise affect any organization that never interacts with billing.
- `stripe_credential` (`app/models/stripe_credential.py`): a single-row table (`id` always `1`) holding the platform-wide Stripe secret API key, Fernet-encrypted (`encrypted_secret_key`), `updated_at`/`updated_by` — structurally identical to `ai_provider_credentials`' encrypt-on-write/decrypt-just-in-time pattern, reusing the existing `settings.ai_credential_encryption_key` (no second encryption key introduced).

### Tier Registry

- `app/billing/tiers.py`: code-owned metadata, mirroring `ProviderRegistry`'s philosophy — `TIERS = {"pro": TierMetadata(stripe_price_id=settings.stripe_price_id_pro, ...), "enterprise": TierMetadata(stripe_price_id=settings.stripe_price_id_enterprise, ...)}`. Free has no registry entry and no Stripe object — it is simply the absence of a `subscriptions` row. Stripe Price IDs come from settings/env, never a hardcoded dollar amount anywhere in this codebase.

### Checkout Flow

- `POST /api/v1/organizations/{organization_id}/billing/checkout` (body `{"tier": str}`), `Depends(require_organization_role(MembershipRole.OWNER))` — the same bar as organization deletion, since this is a financial commitment. Creates or reuses a Stripe Customer for the organization, creates a Stripe Checkout Session (`mode="subscription"`) for the resolved tier's Price ID, and returns the Checkout redirect URL.
- This endpoint never mutates the `subscriptions` table directly — a Checkout session can be abandoned. Only a confirmed webhook event ever changes subscription state.

### Webhook

- `POST /api/v1/billing/webhook` lives entirely outside normal JWT auth — Stripe cannot send a bearer token. Its only trust boundary is cryptographic: `stripe.Webhook.construct_event(raw_body, signature_header, settings.stripe_webhook_secret)` runs **before** any parsing or business logic; a missing/invalid signature is rejected immediately with no DB access. This is a materially different threat model from the public widget's boundary (which trusts a server-derived `public_key`/session and layers on rate limiting/origin checks) — here, the entire boundary is Stripe's HMAC signature, since there is no session or per-request identity to check.
- `STRIPE_WEBHOOK_SECRET` is a deployment-fixed environment variable (like `JWT_SECRET`), never DB-stored or admin-editable — it is generated once when the webhook endpoint URL is registered in the Stripe dashboard, out of band.
- Events handled:
  - `checkout.session.completed` → upsert the `subscriptions` row (customer id, subscription id, tier, `status="active"`).
  - `customer.subscription.updated` → sync `status`/`current_period_end`. Transition to `canceled` → `OrganizationRepository.disable(org, message="This organization's subscription has lapsed.")` (the exact §8a mechanism, not a parallel one). Transition back to `active` (e.g. a recovered card) → `OrganizationRepository.enable(org)`.
  - `customer.subscription.deleted` → same disable path as `canceled`.
  - `invoice.payment_failed` → sync/log only, **never** a disable action — Stripe's own configured retry/dunning window is the actual grace-period mechanism; only the eventual `canceled` status (via `customer.subscription.updated`) triggers disable. A single failed charge never locks an organization out.

### Platform-Admin Manual Override

- `PATCH /api/v1/platform/organizations/{id}/subscription` (body `{"tier": str | None, "status": str | None}`), `Depends(require_platform_admin)` — directly upserts the `subscriptions` row, bypassing Stripe entirely (e.g. to comp an account: `stripe_customer_id`/`stripe_subscription_id` stay `NULL`). A later real webhook event overwrites this row normally via the same upsert path used by `checkout.session.completed` — no special-casing between admin-set and Stripe-set rows.
- Re-enabling a billing-lapsed organization needs no new code — the existing `POST /api/v1/platform/organizations/{id}/enable` (§8a) already covers it.
- A new masked/write-only Stripe secret-key settings field (mirrors BYOK exactly) lives on a new `/platform-admin/settings` page, `Depends(require_platform_admin)`.

### Invoice History

- A self-serve page for the organization owner (`Depends(require_organization_role(MembershipRole.OWNER))`) queries Stripe live (`stripe.Invoice.list(customer=stripe_customer_id)`) on each page load — no locally-synced invoice table. Low-traffic path; Stripe remains the single source of truth for payment records.

## 9. Identity System

### Entities

```text
User <-- Membership --> Organization
```

- **User**: `id`, `email` (unique, normalized lowercase), `password_hash`, `full_name`, `is_active`, timestamps.
- **Organization**: `id`, `name`, `slug` (unique), timestamps. Tenant entity.
- **Membership**: `id`, `user_id` (FK), `organization_id` (FK), `role`, timestamps. Unique on `(user_id, organization_id)`.
- ID strategy: **integer autoincrement** — matches existing placeholder schemas and the current database foundation. UUID would conflict; not adopted.

### Roles

Initial roles (simple, no complex RBAC):

- `owner` — creator of organization, full control.
- `admin` — manages organization resources.
- `member` — standard access.

### Authentication Flow

```text
POST /api/v1/auth/register    -> create user, hash password, return safe user
POST /api/v1/auth/login       -> verify email+password, return access token
GET  /api/v1/auth/me          -> current user (Bearer token)
POST /api/v1/organizations    -> create org + owner membership (transactional)
GET  /api/v1/organizations    -> list orgs current user belongs to
```

### JWT Strategy

- Claims: `sub` (user id), `exp` (expiration), `type` ("access").
- No sensitive data inside the token — user id only.
- Config from settings/env: `secret_key`, `algorithm`, `access_token_expire_minutes`.
- `create_access_token()` / `decode_access_token()` in `core/security.py`.
- **JWT is not authorization.** `get_current_user()` always loads the user from the database and verifies existence + `is_active`.
- Refresh tokens: DB-tracked (refresh_tokens table), single-use with rotation on every use, delivered via an httpOnly cookie (never localStorage — the whole point is keeping it out of XSS's reach). Theft is detected via reuse of an already-rotated token, which revokes the entire token family (family_id) and forces re-login.

### Password Hashing

- bcrypt directly (passlib 1.7.4 is incompatible with bcrypt 5.x — `__about__` removed; passlib is not used).
- `hash_password()` / `verify_password()` in `core/security.py`.
- Only `password_hash` stored; plaintext never persisted or returned.

### Authorization

- `get_current_user()` — validates Bearer token, loads user from DB, checks active.
- `require_organization_membership(organization_id)` — authenticated user must have a membership in the organization (optionally with a required role).
- All organization access paths check membership first.

### Tenant Isolation

- `GET /api/v1/organizations` returns only organizations where the current user holds a membership.
- `POST /api/v1/organizations` creates organization + `owner` membership in one transaction.
- Organization IDs are not exposed as a trust mechanism — membership is always verified.

### Resource Ownership

- Every future organization-owned resource carries `organization_id` and is scoped through membership-verified access.
- Repositories enforce scoping at query time.

## 10. Chatbot Architecture

### Ownership

```text
Organization
    │
    └──< Chatbot
```

- Organization owns chatbot; chatbot carries `organization_id` (FK, required).
- No direct user ownership — chatbot access flows through the organization membership.
- Chatbot cannot exist without an organization.

### Entity

`id`, `organization_id`, `name`, `slug`, `description`, `system_prompt`, `welcome_message`, `status`, `visibility`, `language`, `created_at`, `updated_at`.

- Slug unique **per organization**: DB constraint `(organization_id, slug)`, not globally unique.
- `system_prompt` and `welcome_message` are configuration used by the chat runtime: `system_prompt` is authoritative for the AI gateway, `welcome_message` is surfaced by the widget.
- `language`: string, default `en` (e.g. `en`, `ur`).

### Status

Enum `draft | active | archived`, default `draft`. Creation cannot freely choose status.

Allowed transitions:

```text
draft → active
draft → archived
active → archived
```

`archived → active` is forbidden (no restore endpoint). Invalid transitions return `409 Conflict`.

### Visibility

Enum `private | public`, default `private`. Public visibility enables the public embeddable widget (chatbot must also be `active`).

### Configuration

Chatbot CRUD manages configuration: name, slug, description, system prompt, welcome message, language, visibility, and provider/model selection (validated against the provider/model registries). Provider/model credentials are never stored on the chatbot.

### Lifecycle

`draft` (default on create) → `active` (activate) → `archived` (archive). Update/PATCH changes config fields only; immutable fields (`id`, `organization_id`, `created_at`, `updated_at`) can never be changed.

### Tenant Isolation

Every chatbot query is scoped by `organization_id`. Repository exposes `get_by_id_for_organization()` and `list_for_organization()` only — no unsafe global `get_by_id()`. Endpoint authorization chain: authenticated → organization exists → user is member → role allowed → chatbot belongs to that organization.

### Role Permissions

| Role   | Read | Create | Update | Activate | Archive | Delete |
| ------ | ---- | ------ | ------ | -------- | ------- | ------ |
| owner  | YES  | YES    | YES    | YES      | YES     | YES    |
| admin  | YES  | YES    | YES    | YES      | YES     | YES    |
| member | YES  | NO     | NO     | NO       | NO      | NO     |

Enforced once via reusable `require_organization_role(...)` dependency — role checks are not duplicated in routes.

### Deletion Strategy

- MVP: controlled hard delete. Deleting a chatbot cascades its dependent data (conversations/messages, knowledge documents/chunks, widget configs/sessions via FK ON DELETE CASCADE).
- Deleting a chatbot never deletes the organization (FK from chatbot to organization is non-cascading from organization side).

### Future Integration Seams

- **AI provider abstraction**: chatbot stays provider-agnostic; provider choice is a runtime config concern.
- **RAG/knowledge**: future tenant-scoped document/vector stores keyed off the same organization, behind a vector abstraction.
- **Widget**: future embedding runtime; public visibility will gate it, but nothing public exists yet.

## 11. Conversation & Message Architecture

### Ownership

```text
Organization
    ↓
Chatbot
    ↓
Conversation
    ↓
Message
```

- Conversation belongs to exactly one chatbot and one organization.
- Conversation carries `organization_id` explicitly (in addition to `chatbot_id`) so tenant-scoped queries are explicit and safe.
- `user_id` = authenticated creator/owner of the conversation.
- Message belongs to exactly one conversation; conversation never crosses organization boundary.
- Service verifies `conversation.organization_id == chatbot.organization_id` on creation — client organization/chatbot ids are never trusted.

### Conversation

Fields: `id`, `organization_id`, `chatbot_id`, `user_id`, `title`, `status`, `created_at`, `updated_at`.

- Status enum `active | archived`, default `active`. Only transition `active → archived` (archive). Archived conversations stay readable but reject new messages. No restore.

### Message

Fields: `id`, `conversation_id`, `role`, `content`, `sequence_number`, `created_at`, `metadata`.

- MVP roles: `system`, `user`, `assistant` (future `tool`). Client may create only `user`; `system`/`assistant` are server-side only. No arbitrary system-message API.
- Content is text (PostgreSQL `TEXT`). No multimodal content yet.
- Messages are **immutable**: no PATCH, no DELETE. History may later feed analytics, RAG, debugging, usage, audit.

### Ordering & Concurrency

- Ordering by `sequence_number` (starts at 1), enforced `UNIQUE(conversation_id, sequence_number)` — never rely on timestamps alone.
- Server assigns sequence numbers; client never provides them.
- MVP concurrency: message creation is transactional; the repository reads the latest sequence and inserts `latest + 1`; the unique constraint rejects races (surface as conflict/retry later). Documented as MVP approach — a row-lock/atomic counter is a future refinement.

### Pagination

- List messages: `limit` + `offset`, `sequence_number ASC`, default limit 50, max limit 200. Never load unlimited history.
- Cursor pagination documented as future refinement.

### Metadata

- Message `metadata` is optional JSONB: future provider metadata, citations, runtime info, UI metadata. No secrets.

### Role Permissions

- All members: create conversations, read permitted conversations, read messages, create user messages.
- Archive: owner/admin → any organization conversation; member → own conversations only.
- Read policy: member → own conversations; owner/admin → all organization conversations.
- Member cannot modify/access another member's conversation.

### Deletion Policy

- No conversation DELETE endpoint. Archive only. Permanent deletion policy comes later (history may support analytics, RAG, debugging, usage, audit, support). Rename (`PATCH`, `title` only) exists alongside archive, with the same owner/admin-any + member-own permission rule as archive; rename is blocked on an archived conversation — the same frozen-state rejection that already blocks new messages.

### Tenant & Chatbot Isolation

- Every conversation/message query is scoped by organization. Repositories expose tenant-safe methods only.
- Org A users can create conversations only for Org A chatbots — knowing a foreign chatbot id grants nothing.
- `message_id` alone never grants access; message access flows through conversation ownership.

### AI Runtime

```text
User Message → Conversation Service → AI Runtime → Chatbot Config → AI Gateway → Provider → Assistant Message
```

Implemented (see §12). Normal and SSE-streaming turns persist the user message, build history + RAG context, call the AI Gateway once, and persist one assistant message. WebSocket transport, tool calling, usage tracking, and richer RAG controls are future additions against these same contracts.

## 12. Chat Runtime Architecture

### Responsibilities

`ChatRuntimeService` (`app/services/chat_runtime.py`) orchestrates one chat turn:

1. Authenticate user, verify organization membership, verify conversation access (Step 6 rules: member → own, owner/admin → any).
2. Verify conversation is `active` — archived → 409 before any write or gateway call.
3. Verify chatbot/conversation consistency (`conversation.chatbot_id`).
4. Save user message (server-assigned sequence), commit.
5. Retrieve ordered history (sequence ASC) including the new user message.
6. Build provider-neutral `AIRequest` from chatbot config + history.
7. Call `AIGateway` (outside the DB transaction).
8. Save assistant message from `AIResponse`, commit.
9. Return response DTO.

```text
User → POST /chat → Router → ChatRuntimeService → Repositories → AIGateway → ProviderRegistry → Provider
```

### Request/Response Flow

- Request DTO: only `{"content": "..."}` with `extra="forbid"`; empty/whitespace content rejected.
- Client cannot control `organization_id`, `chatbot_id`, `conversation_id`, `role`, `sequence`, `provider`, `model`, or `system_prompt` — all come from trusted server resources/config.
- Response DTO: `conversation_id` + `user_message` + `assistant_message` (Pydantic DTOs, never raw DB/provider objects).

### Conversation History & System Prompt

- History = persisted messages ordered `sequence_number ASC` (includes the just-saved user message).
- `AIRequest.system_prompt = chatbot.system_prompt`; system prompt is **not** stored as a system Message.
- `messages` = conversation history as `AIMessage` (user/assistant roles).
- Chatbot `welcome_message` is preserved only — never stored as a Message; future widget/UI may use it.

### Gateway Integration

- Runtime calls `AIGateway` only — never provider adapters directly, no provider SDKs, no `if/elif` on provider ids.
- Uses existing `app/ai/registry.py` gateway singleton.
- `AIResponse.content` persisted as assistant message; safe metadata (`provider_id`, `model_id`, `finish_reason`) may be stored; never API keys/secrets/raw SDK objects.

### Transaction Boundaries & Failures

1. Save user message → commit.
2. Call AI outside DB transaction.
3. Save assistant message → commit.

AI failure: user message remains committed, assistant message NOT created, conversation stays valid and retryable. Error responses are normalized — no stack traces, API keys, or provider internals. Archived conversation → 409 with no DB changes and no gateway call.

### Idempotency

Not implemented. Each POST /chat creates exactly one user message and (on success) one assistant message. Idempotency keys are a future refinement.

### Observability

Runtime context available for future logging/telemetry: `organization_id`, `chatbot_id`, `conversation_id`, `user_id`, `provider_id`, `model_id`. No analytics built. Passwords, JWT secrets, API keys, provider credentials, and full user prompts are never logged by default.

### Future Seams

- Streaming: `AIRequest`/`AIResponse` contracts support future streaming extension.
- RAG: history/context assembly point in `ChatRuntimeService` is the seam.
- Tools/agents: `AIRequest` messages extension point.
- Usage tracking: `AIResponse.usage` already normalized; persistence is future.

## 13. AI Gateway Architecture

### Core Flow

```text
Application
    ↓
AI Gateway
    ↓
Provider Registry
    ↓
Provider Adapter
    ↓
Provider API
```

- Application code never imports or calls provider SDKs directly (OpenAI, Anthropic, Gemini, Kimi, DeepSeek, Qwen, Mistral, Groq, OpenRouter, etc.).
- Provider-specific logic lives only in adapters under `app/ai/providers/`.
- The gateway never branches on provider ids — no `if provider == "openai"` chains. It always resolves via `registry.get(provider_id)`.

### Provider ≠ Model

- `provider_id` and `model_id` are independent, extensible strings. Never a giant enum.
- Example: provider `kimi`, model `kimi-k2-0711`; later model `kimi-k3` is only a registration.
- No DB enums for providers/models.

### Provider Metadata

`provider_id`, `display_name`, `description`, `enabled`, `base_url`, `authentication_type` (`api_key`, `none`), `compatibility_type` (`openai_compatible`, `native`, `fake`), `capabilities`.

- Never stores API secrets.

### Model Metadata

`provider_id`, `model_id`, `display_name`, `context_window`, `max_output_tokens`, `capabilities`, `enabled`.

- Future optional fields (no billing yet): `input_price`, `output_price`, `currency`, `reasoning_support`, `deprecated`, `release_date`.

### Capabilities

`TEXT_GENERATION`, `STREAMING`, `TOOL_CALLING`, `STRUCTURED_OUTPUT`, `VISION`, `AUDIO_INPUT`, `AUDIO_OUTPUT`, `EMBEDDINGS`, `IMAGE_GENERATION`, `JSON_MODE`, `REASONING`.

- Capabilities belong primarily to model metadata; provider metadata carries broad capabilities.
- Only `TEXT_GENERATION` is implemented now. Others are abstraction + capability checks only.

### Normalized Contracts

- `AIMessage`: `role` (system/user/assistant; future tool) + `content`.
- `AIRequest`: `provider_id`, `model_id`, `messages`, `system_prompt`, `temperature`, `max_tokens`, `metadata`, `response_schema` (implemented — see "Structured Output" below), `tools` (implemented — see "Tool Calling (Surface-Only)" below). Future extension points: stream, attachments, images, audio.
- `AIResponse`: `content`, `provider_id`, `model_id`, `finish_reason`, `usage`, `metadata`, `tool_calls` (implemented — see "Tool Calling (Surface-Only)" below).
- `AIUsage`: `input_tokens`, `output_tokens`, `total_tokens`.
- Application always receives PortableAI objects, never provider SDK response objects.

### Provider Interface

```python
class AIProvider(Protocol):
    metadata: ProviderMetadata
    async def generate(self, request: AIRequest) -> AIResponse: ...
```

- Provider-independent, FastAPI-independent, SQLAlchemy-independent, DB-independent.
- Adapters translate `AIRequest → provider request → provider API → provider response → AIResponse`.

### Registries

- `ProviderRegistry`: `register`, `get`, `list`, `exists`.
- `ModelRegistry`: `register`, `get(provider_id, model_id)`, `list(provider_id)`, `exists(provider_id, model_id)`.
- Supports many models per provider. Duplicate registration raises.

### AI Gateway

Responsibilities: validate request → resolve provider → resolve model → check provider enabled → check model enabled → check model belongs to provider → check required capabilities → call adapter → normalize response → normalize errors.

- Contains zero provider-specific code.
- Gateway errors are provider-neutral (`app/ai/exceptions.py`): `AIError`, `AIProviderError`, `AIAuthenticationError`, `AIRateLimitError`, `AIInvalidRequestError`, `AIModelNotFoundError`, `AIProviderUnavailableError`, `AICapabilityNotSupportedError`.
- Adapters translate SDK/provider exceptions into these; API never sees SDK exceptions.

### OpenAI-Compatible Providers

- `OpenAICompatibleProvider` abstraction for future OpenAI, Kimi, DeepSeek, Qwen, Groq, Together, Fireworks, custom endpoints.
- Adapters must not assume identical behavior; provider/model metadata defines capabilities, limits, errors, endpoint differences.

### Dynamic Providers and Models

- Built-in: providers/models registered in code (`app/ai/registry.py`).
- Dynamic (future): configured at runtime (new provider, new model, custom OpenAI-compatible endpoint, org provider, newly released model).
- Adding a model requires only model metadata + registration. No DB migration, no gateway/service/route changes.
- Adding a provider requires only adapter + provider metadata + models + registration + tests.

### Credential Isolation

- Provider API keys are never stored in chatbots, organizations, provider metadata, model metadata, JWT, logs, or source code.
- BYOK (bring-your-own-key): `ai_provider_credentials` stores an organization-scoped, Fernet-encrypted API key per (organization, provider_id) — `provider_id` matches the code registry's `provider_id` but is a plain string, not a DB FK, since providers stay code-registered. Unique on `(organization_id, provider_id)`.
- Encryption: `cryptography`'s Fernet, keyed by `AI_CREDENTIAL_ENCRYPTION_KEY` (required, environment-only, fail-fast at startup if missing — never stored in the DB). Known MVP limitation: there is no key-rotation mechanism; losing the encryption key makes every stored credential permanently undecryptable.
- Resolution seam: `AIProvider.generate`/`.stream` and `AIGateway.generate`/`.stream` take an optional `credential_override: str | None = None` (default `None`, every existing call site unchanged). `ChatRuntimeService` resolves an org's BYOK credential via `AIProviderCredentialService` at both existing gateway call sites (next to the M5 enable/disable override check), decrypts it just-in-time, and passes it through — plaintext is never held longer than that single call, never logged. Absent a BYOK credential, the platform-shared environment credential is used, unchanged from today's behavior.
- Save-time validation: setting a credential makes a minimal live test call against the provider before it is ever encrypted or stored; a failing call is rejected with a 4xx and nothing is persisted.
- Admin UI is write-only: the actual key is never re-displayed, only a masked last-4 indicator (e.g. `••••••••1234`) plus who last updated it and when.
- BYOK is orthogonal to the M5 provider/model enable/disable override: BYOK changes which credential is used for an already-available provider/model, never whether it is available — a disabled provider/model stays unavailable regardless of BYOK.
- Permission: ADMIN+ (owner/admin), matching existing org-level sensitive-mutation precedent (widget-config, chatbot creation).
- Explicitly out of scope: per-user keys, rotation reminders/expiry, multiple keys per provider, usage/cost attribution by key.

### Chatbot AI Configuration

- Chatbot gains `provider_id` and `model_id` string columns (defaults from the default registry entry, e.g. provider `fake`, model `fake-model-small`).
- Defaults are defined in the registry, never hardcoded in `ChatbotService`, routes, or `AIGateway`.
- New model never requires migration; new provider never requires core chatbot business-logic changes.

### Structured Output

- Schema source: `chatbots.response_schema` (nullable JSON), chatbot-level config — not per-request — mirroring the `rag_enabled`/`rag_top_k` precedent. NULL keeps today's free-text behavior completely unchanged.
- Capability gate: `AIGateway.generate`/`.stream` require `AICapability.STRUCTURED_OUTPUT` (never the looser `JSON_MODE` member) whenever `AIRequest.response_schema` is non-`None` — the gateway derives this itself from the request, callers never need to pass it explicitly. A model without the capability registered is rejected before any provider call is made, via the same capability-check mechanism already used for `TEXT_GENERATION`/`STREAMING`.
- Provider adapter: the OpenAI-compatible adapter's `_build_payload` adds `response_format` using the schema-validated `json_schema` shape (`strict: true`), not the loose `json_object` mode, when a schema is present.
- Validation: the platform never trusts a provider's json-mode guarantee blindly. `ChatRuntimeService` parses the response as JSON and validates it against the schema (the `jsonschema` package) before ever persisting it. On failure, it retries **exactly once** — the model's invalid reply plus a description of the validation error are appended to the conversation as an ordinary user-role message (the same precedent `ContextBuilder` already uses for injecting non-human context; there is no tool role in this codebase and none was added for this) — and validates the retry. If the retry is still invalid, `ChatRuntimeService` raises the existing adapter-boundary error (`AIInvalidRequestError`, already mapped to a 502-class response) and persists nothing.
- Streaming: schema validation needs the complete response before it can be judged valid, so a structured-output chatbot's streaming turn makes a single non-streaming `AIGateway.generate` call (with the same validate/retry-once logic) internally and emits one buffered SSE `token` event with the full validated content, followed by `end` — the SSE event shape is unchanged, so the frontend needs no changes. A chatbot with `response_schema` unset keeps today's true incremental `AIGateway.stream` path exactly as before.
- Capability registered on: the `gemini` model only, based on a documentation review, not a live API test call (no real Gemini credentials are available in this environment). Google's official docs confirm Gemini models support schema-constrained JSON output, but document that via the OpenAI SDK's `.beta.chat.completions.parse()` helper or Gemini's native `responseSchema`/`responseMimeType` field — neither page explicitly confirms the raw `response_format: {"type": "json_schema", "strict": true}` HTTP payload this adapter actually sends over the OpenAI-compatible endpoint. A non-authoritative community forum post claims that exact raw shape works, and separately notes Gemini only supports a subset of the JSON Schema specification (unsupported keywords are silently ignored). **This capability flag is an unverified assumption and should be validated against a live Gemini API call before being relied on in production.** The built-in fake providers do not carry this capability by default; tests that need a capability-bearing double register one locally, the same way other AI-gateway tests already swap in a scoped test provider.

### Tool Calling (Surface-Only)

- Tool definitions: `chatbots.tools` (nullable JSON), a list of `{"name", "description", "parameters"}` objects (parameters is a JSON Schema dict) — chatbot-level config, optional, mirroring `response_schema`'s precedent exactly. NULL/empty keeps today's behavior completely unchanged.
- Capability gate: `AIGateway.generate`/`.stream` require `AICapability.TOOL_CALLING` whenever `AIRequest.tools` is non-`None` — same auto-derived mechanism as `STRUCTURED_OUTPUT`.
- Provider adapter: the OpenAI-compatible adapter's `_build_payload` wraps each tool definition into the `{"type": "function", "function": {...}}` envelope and adds it to `payload["tools"]` when present. `_parse_response` extracts `choice["message"]["tool_calls"]` into `AIToolCall(id, name, arguments)` instances — `arguments` is stored as the raw, provider-returned JSON-encoded string, never pre-parsed or validated against the tool's declared parameter schema (unlike structured output's response validation, there is no retry loop here — a tool-call request passes through as-is).
- Persistence: no new `MessageRole` — a tool-call request is an ordinary `ASSISTANT`-role message. `content` is a backend-constructed, human-readable summary (e.g. `Requested tool call: get_weather({"location": "Boston"})`) rather than left empty, so the existing chat bubble stays meaningful with zero frontend changes; the structured `tool_calls` data (id, name, raw arguments string) rides in the existing generic `metadata` JSON column, the same place `provider_id`/`model_id`/`finish_reason` already live.
- Streaming: a tools-configured chatbot's streaming turn uses the same single buffered `AIGateway.generate` call inside `stream_turn()` that structured output already established, emitting one `token` + `end` SSE pair — real incremental tool-call-delta streaming (reassembling fragmented name/arguments chunks) is not implemented. A chatbot with `tools` unset keeps today's true incremental `AIGateway.stream` path exactly as before.
- `tool_choice` is not supported; the provider's default (`"auto"`) behavior applies. Server-side execution is now implemented — see "Tool Execution (Platform-Defined Allowlist)" below.

### Tool Execution (Platform-Defined Allowlist)

- Registry: `app/ai/tools/` mirrors the existing `app/ai/providers/` pattern — `base.py` defines a `Tool` protocol (`name`, `description`, `parameters_schema`, `async def execute(arguments: dict, *, organization_id, chatbot_id, db_session) -> str`); `registry.py` defines `ToolRegistry` (`register`/`get`/`list`/`exists`, `DuplicateToolError`) mirroring `ProviderRegistry` exactly; a default `tool_registry` singleton is built alongside `gateway`/`provider_registry`/`model_registry` in `app/ai/registry.py`. Platform-context parameters (`organization_id`, `chatbot_id`, `db_session`) are passed to `execute()` separately from model-supplied `arguments` — never merged — so a tool can never be pointed at a different tenant's data via its arguments, structurally, not just by validation.
- Initial allowlist (exactly 3, no more):
  - `get_current_datetime(timezone: str | None)` — returns an ISO-8601 string via stdlib `zoneinfo`; an invalid timezone name produces a clean tool-result error, never a crash. Safe: pure read of the server clock, zero I/O beyond the OS's already-trusted tz database.
  - `calculate(expression: str)` — parses via `ast.parse(expr, mode="eval")` and evaluates only `Constant`, `BinOp` (`+ - * / // % **`), `UnaryOp` (`+ -`), and a tiny explicit whitelist of pure functions (`abs`/`round`/`min`/`max`); any other AST node (`Name`, `Attribute`, a non-whitelisted `Call`, `Subscript`, comprehensions, ...) is rejected with a clean tool-result error. Never calls `eval()`/`exec()` on raw text under any circumstance — this is a restricted-grammar arithmetic evaluator, not a sandboxed interpreter.
  - `search_knowledge_base(query: str, top_k: int = 5)` (`1 <= top_k <= 10`) — wraps the existing `RetrievalService.search(organization_id, chatbot_id, query, top_k)` with zero duplicated logic. `organization_id`/`chatbot_id` come from the current turn's trusted server-side context only, never from model-supplied tool-call arguments.
- Chatbot tool selection: `chatbots.tools` entries are validated at save time — any `"name"` not in `tool_registry.exists(name)` is rejected with a clear 4xx, matching this project's "reject clearly, don't silently accept" precedent (BYOK, structured output, provider/model validation). The admin's stored `description`/`parameters` become effectively vestigial once the name is validated: at request-build time, the tool definition actually sent to the model (description, parameters schema) comes from the registry, not from the stored JSON — only the name is load-bearing. The admin UX stays validated-freeform-JSON for this milestone; a checkbox-selection UI drawing directly from the registry is a natural fast-follow, not required for correct/safe execution.
- Execution loop: `ChatRuntimeService._run_with_tool_execution()` (mirroring `_generate_structured()`'s shape) replaces the single `gateway.generate()` call at `chat()`'s and `stream_turn()`'s tools-configured branches. Capped at 5 total gateway calls per turn; the 5th call omits `tools` entirely, structurally forcing a text-only final answer rather than failing the turn when the cap is reached.
- Persistence: intermediate tool-call-request/tool-result exchanges stay ephemeral — in-memory `AIMessage` objects only (via two new optional `AIMessage` fields, `tool_calls: list[AIToolCall] | None` and `tool_call_id: str | None`, and `AIMessageRole.TOOL`, contract-level only), never written to the `messages` table — mirroring the existing structured-output retry-once precedent of ephemeral intermediate exchanges. Only the turn's final text answer is persisted as the one `ASSISTANT` message, preserving "one turn = one persisted assistant message" exactly. Because intermediate exchanges are never persisted, **no `MessageRole.TOOL` value and no migration are needed** — `MessageRole` stays `SYSTEM`/`USER`/`ASSISTANT`, unchanged. To preserve auditability on this platform's first code-execution surface despite the ephemeral design, a full `tool_execution_trace: list[{iteration, name, arguments, result}]` rides in the final persisted message's `metadata`, alongside the existing `provider_id`/`model_id`/`finish_reason`.
- Timeout & failure handling: a tool execution failure or timeout becomes a clean, generic error-shaped tool result fed back to the model (with the matching `tool_call_id`) — never a raw traceback, never logged with sensitive detail, never a whole-turn failure. New centralized setting `tool_execution_timeout_seconds: float = 5.0` (`app/core/config.py`, following the `openai_timeout`/`url_fetch_timeout` convention), enforced via `asyncio.wait_for`.
- Mutual exclusion with structured output: a chatbot with **both** `tools` and `response_schema` configured keeps tool calls surface-only/unexecuted — exact pre-milestone behavior for that combination (see "Tool Calling (Surface-Only)" above, still accurate for this case). Only `tools`-without-`response_schema` gets real execution. Combining the two is a distinct future refinement, not designed against here.
- Streaming: zero new SSE event types. The existing buffered branch (`start` → one `token` → `end`) is unchanged in shape — tool execution happens invisibly inside the loop before that single `token`/`end` pair is emitted. A frontend visual indication of tool execution in progress remains a distinct, separately-scoped future capability.

### Transient Provider Error Retry

- Lives entirely inside `AIGateway` (`app/ai/gateway.py`), not the provider adapter — provider-and-request-agnostic, so every adapter benefits automatically and the gateway's existing "never branches on provider ids" principle holds. No new dependency; a small hand-rolled retry loop, consistent with this codebase's existing hand-rolled structured-output-retry precedent (no `tenacity` or similar is installed).
- Retried: `AIProviderUnavailableError` only — the adapter already maps 408/502/503/504 and `httpx.TimeoutException`/`httpx.HTTPError` to this one exception type. Never retried: `AIRateLimitError` (429 — retrying immediately would compound a provider-side throttle; deferred, would need `Retry-After` header plumbing and a different backoff posture), `AIAuthenticationError`, `AIInvalidRequestError`, `AIModelNotFoundError`, `AICapabilityNotSupportedError`, or a generic `AIProviderError` — all propagate immediately on first occurrence, exactly as before this milestone.
- Attempts: 3 total (1 original + 2 retries), bounded, not open-ended.
- Backoff: exponential with jitter — base 300ms, ×2 per attempt, capped at 2s, plus small random jitter to avoid synchronized retry storms across concurrent requests during genuine provider-wide congestion.
- `AIGateway.generate()`: the entire `provider.generate()` call is atomic (one HTTP request/response), so it is wrapped wholesale in the retry loop — no partial-output concern. This one change automatically also covers `stream_turn()`'s two buffered branches (structured output, tool calling — both call `gateway.generate()` internally per their own sections above), with no separate retry logic needed for either.
- `AIGateway.stream()`: restructured from "resolve/validate then return `provider.stream(...)` directly" into a real `async def` generator. It retries the underlying `provider.stream(request, ...)` call (a fresh connection) only while **zero token-type stream events have been forwarded to its caller so far in this invocation** — not based on exception type or elapsed time. The moment one token event is yielded to the caller, the retry window closes permanently for that call; any later failure in the same call propagates exactly as it does today (an SSE `error` event — matching §20's existing "headers already sent, HTTP status can't change" precedent, unchanged). Non-token events (e.g. an adapter-internal `start` event, which fires before any HTTP call is even made) never count as "output shown" and never close the retry window by themselves.
- Observability: each retry attempt is logged at WARNING — `provider_id`, `model_id`, attempt number, exception class only. Never the response body, headers, or any credential/secret value, matching this project's existing zero-secret-leak logging discipline (§29).
- Exhaustion behavior is unchanged: after all attempts are exhausted, `ChatRuntimeService.chat()` still raises `RuntimeErrorAI(502, "AI provider unavailable")`; `stream_turn()` still surfaces the equivalent SSE `error` event. This milestone only reduces how often that path is reached — the ultimate-failure UX is untouched.
- `ChatRuntimeService.chat()`/`stream_turn()` require zero changes — retry is entirely internal to `AIGateway`; both call sites are unaffected.

### Future Extensions

Vision/multimodal, fallback providers, retries, local models, BYOK, usage tracking, provider/model administration — all planned against these contracts. Streaming and embeddings are already implemented (see §14, §18–§20).

## 14. Real Provider Integration

### Architecture

```text
Application → AI Gateway → Provider Adapter → HTTP API
```

- The real provider (OpenAI-compatible) is an **extension**, not a rewrite: it plugs into the existing `AIProvider` contract, `ProviderRegistry`, `ModelRegistry`, `AIGateway`, and `ChatRuntimeService` unchanged.
- Application code never calls provider HTTP directly; the adapter owns all HTTP.
- The gateway contains no provider-specific branching — it always resolves via `registry.get(provider_id)`.

### OpenAI-Compatible HTTP Architecture

- Concrete adapter `app/ai/providers/openai_compatible.py` subclasses the existing `OpenAICompatibleProvider` base.
- `httpx.AsyncClient` (already a dependency) with explicit unified timeout — external calls never hang indefinitely.
- One runtime request = one provider call. **No automatic retries**; retry/backoff/idempotency/fallback/circuit-breaker are future seams.

### Request Conversion

- Adapter receives provider-neutral `AIRequest` and builds the external OpenAI-style payload: `model` from `model_id`, `messages` from history, `system_prompt` as the leading system message (authoritative, never duplicated, never stored as a DB Message), plus `temperature`/`max_tokens` when set.
- `metadata` is not sent to the provider.
- Runtime never sees the provider HTTP schema.

### Response Normalization

- External response → existing `AIResponse` (content, provider_id, model_id, finish_reason, `AIUsage` tokens, metadata).
- Raw provider JSON never escapes the adapter.

### Credentials & Base URL

- API key, base URL, and timeout come from centralized settings (`app/core/config.py`), env vars `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_TIMEOUT`.
- Key is never stored in DB, chatbot, organization, provider/model metadata, JWT, logs, source, migrations, or `AIResponse`.
- Missing key → provider registered but **disabled** (clear failure at runtime, never silent unauthenticated calls).

### Model & Provider Registration

- `provider_id = "gemini"` (display name "Google Gemini" — Google's OpenAI-compatible API), model id from config/env (`OPENAI_MODEL`; code default `gpt-4o-mini`, deployments set it explicitly, e.g. `gemini-3.6-flash`) registered through existing registries — extensible strings, no enums.
- Enablement reuses `ProviderMetadata.enabled` / `ModelMetadata.enabled`; fake providers stay enabled for offline tests.

### Error Mapping

Adapter maps HTTP statuses to normalized exceptions: 400 → `AIInvalidRequestError`, 401/403 → `AIAuthenticationError`, 404 → `AIModelNotFoundError`, 429 → `AIRateLimitError`, 408/502/503/504/timeout → `AIProviderUnavailableError`, malformed response / other → `AIProviderError`. Client errors never contain API keys, auth headers, sensitive request data, stack traces, or unsafe internals.

### Security Boundaries

- Credentials live only in environment/config.
- Chatbot API cannot set credentials (`extra="forbid"` on chatbot schemas; no credential fields exist).
- Cross-tenant access unchanged (existing membership/RBAC/repository scoping).

### Testing

- All provider tests use mocked HTTP — no network, no key required.
- Default `pytest` stays offline/deterministic (fake provider default).
- Optional live smoke test runs only if a valid `OPENAI_API_KEY` is configured.

## 15. Provider & Model Management Architecture

### Registry as Runtime Source

- Providers/models live in `ProviderRegistry` / `ModelRegistry` (config/code-based, no DB tables).
- Management APIs are a **read-only discovery view** over the registries — they never bypass or redesign `AIGateway`.

```text
Client → AI Management API → AIManagementService → ProviderRegistry / ModelRegistry → Safe DTO
```

### API Boundary

- Endpoints: `GET /api/v1/ai/providers`, `GET /api/v1/ai/providers/{provider_id}`, `GET /api/v1/ai/providers/{provider_id}/models`, `GET /api/v1/ai/providers/{provider_id}/models/{model_id}`.
- All require authentication (`get_current_user`).
- Routers stay thin; `AIManagementService` (`app/services/ai_management.py`) owns registry access and validation.
- Safe Pydantic DTOs (`ProviderResponse`, `ModelResponse`) — raw registry objects never returned.

### Credential Visibility

**Provider credentials are NEVER returned by management APIs.**

- Responses contain only safe metadata: provider_id, display_name, description, enabled, authentication_type, compatibility_type, capabilities (providers); provider_id, model_id, display_name, context_window, max_output_tokens, enabled, capabilities (models).
- `base_url` and any credential-bearing fields are excluded from DTOs.
- `enabled: false` for the real provider (Gemini) without a key — no sensitive explanation of missing credentials.

### Platform vs Tenant Config

- Providers/models are **platform infrastructure**; authenticated users may discover them.
- Mutation is enable/disable only, never add/remove — new providers/models are still registered exclusively in code (`app/ai/registry.py`); the API can only toggle availability of what code already registers.
- Mutation is gated by `require_platform_admin()`, a dependency independent of `require_organization_role` — no `MembershipRole`, including `OWNER`, satisfies it. Platform-admin status grants no access to any organization's message/conversation content, `system_prompt`, or credential material — with one narrow, explicit exception: the platform dashboard's aggregate/metadata-only reads across organizations (§8a), via `require_platform_admin()`-gated endpoints only. No other route, and no other data category, is affected.

### Platform Admin Mutation

```text
PATCH /api/v1/ai/providers/{provider_id}        {"disabled": bool}
PATCH /api/v1/ai/providers/{provider_id}/models/{model_id}   {"disabled": bool}
```

- `AIProviderOverrideService` (`app/services/ai_provider_override.py`) owns `ai_provider_overrides` / `ai_model_overrides` — thin tables storing only `disabled_at`/`disabled_by` per `provider_id` (or `(provider_id, model_id)`); no provider/model metadata is duplicated from the registries.
- Effective enablement is `registry.enabled AND override.disabled_at IS NULL` — the DB can only narrow what code allows, never widen it. A provider/model absent from the override table behaves exactly as it does today (default: not disabled).
- The check is added at the two existing call sites that already gate on `.enabled` — `ChatbotService._validate_provider_model()` and `ChatRuntimeService.chat()`/`stream_turn()` — both of which already hold an `AsyncSession`. `AIGateway` itself is unmodified and stays DB-independent.
- Disabling blocks both new chatbot assignment (`422 InvalidProviderModelError`, same error the code-disabled case already produces) and execution of chatbots already configured with it (existing `RuntimeErrorAI` mapping via the gateway's existing `AIProviderUnavailableError`/`AIModelNotFoundError`) — no new error types, no new HTTP statuses.
- `disabled_at`/`disabled_by` on the override row are the audit trail for this action; no separate audit-log subsystem exists or is introduced by this feature.

### Chatbot Provider/Model Validation

- On chatbot create/update, validate through the registries: provider exists → provider enabled → model exists → model belongs to provider → model enabled.
- Reject unknown provider, unknown model, model from another provider, disabled provider, disabled model.
- Validation lives in `ChatbotService` via registry checks — no duplicated logic, no bypass.

### Future Extension Points

- Full DB-backed provider/model CRUD (creating new providers/models via API, not just toggling code-registered ones) remains out of scope; registration stays code-only.
- A full historical audit log of every enable/disable event (beyond the current-state `disabled_at`/`disabled_by`) is a possible future enhancement, not required today.
- Capability-based provider/model filtering for the dashboard.

## 16. RAG / Knowledge Architecture

### Ownership

```text
Organization → Chatbot → Document → Chunk → Embedding
```

- Every knowledge operation is scoped by `organization_id + chatbot_id`. No global lookup by ID alone.
- A knowledge document belongs to exactly one chatbot; a chunk belongs to exactly one document.

### Document Lifecycle

- Status: `pending → processing → ready`; failure `processing → failed`; retry `failed → processing`.
- Server owns status — client never sets it.
- Hard delete for MVP (deletes document + chunks + vectors); documented decision; no cross-tenant deletion.

### Pipeline (ingestion)

```text
Document → Normalize → Chunk → Embed → Store → ready
```

- `TextNormalizer`: normalize line endings, collapse repeated whitespace, preserve meaningful text, reject empty.
- `Chunker`: deterministic whitespace-based, configurable chunk size + overlap, preserves order. Token-aware chunking is future.
- Embeddings via `EmbeddingProvider` abstraction — RAG code never contains provider-specific embedding logic.

### Embedding Abstraction

- `EmbeddingProvider.embed_texts(texts) → vectors`; `EmbeddingMetadata` (provider_id, model_id, dimensions).
- MVP uses deterministic offline `FakeEmbeddingProvider` (stable vectors, configured dimension, no network/key) by default.
- Real embedding providers are registered via the same abstraction; `openai` (OpenAI-compatible HTTP) is implemented and enabled when `OPENAI_API_KEY` is present. Other providers are future.
- Embedding model is independent of text-generation model; dimension centralized in config (default 384).

### Vector Storage

- pgvector column on `document_chunks` (cosine distance, dimension 384 — one dimension for MVP, centralized, never scattered).
- `UNIQUE(document_id, chunk_index)`; indexes on organization_id, chatbot_id, document_id.

### Similarity Search

- `RetrievalService`: query text → query embedding → tenant-scoped hybrid search (pgvector cosine similarity + Postgres full-text search) → top-k chunks.
- Hybrid ranking: `ChunkRepository` runs two candidate queries per search — cosine-distance `ORDER BY` on `document_chunks.vector` (existing HNSW index) and `ts_rank_cd` `ORDER BY` on a new `content_tsv` generated column (new GIN index), each `LIMIT candidate_pool` (`candidate_pool = top_k * 4`) — fused via Reciprocal Rank Fusion (RRF, `score = Σ 1/(k + rank_i)` across whichever list(s) a chunk appears in, k=60): no cross-scale score tuning, standard technique, no new runtime dependency.
- Required scope: `WHERE organization_id = X AND chatbot_id = Y` on both candidate queries. Never global vector search.
- Returns `RetrievedChunk` DTOs (document_id, chunk_id, content, score, metadata) — never ORM objects or raw vectors. `search(organization_id, chatbot_id, query, top_k)` is unchanged — fusion is entirely internal, so `ContextBuilder` and per-chatbot `rag_enabled`/`rag_top_k` (§17) compose transparently, unaffected.

### Tenant & Chatbot Isolation

- Org A chatbot A can never see Org B chatbot B chunks — even with identical queries.

### Deletion & Re-indexing

- Deletion: hard delete (document + chunks + vectors). Automatic re-indexing is future.

### Runtime Integration

```text
User Message → Retrieval → Context Builder → AIGateway → Assistant
```

Implemented (see §17). `RetrievalService` + `ContextBuilder` are wired into both normal and streaming chat. Future: reranking, semantic cache, document versioning, background workers.

## 17. RAG Runtime Integration / Context Assembly

### Runtime Flow

```text
User Message → ChatRuntime → RetrievalService → ContextBuilder → AIRequest → AIGateway → Provider → Assistant Message
```

- RAG sits **above** `AIGateway`; the gateway stays provider-agnostic.
- Flow: authorize → save user message (commit) → history → retrieve (server-side `organization_id` + `chatbot_id`, latest user content) → `ContextBuilder` assembles → call gateway once → save assistant message (commit).

### Context Assembly (ContextBuilder)

`app/services/context_builder.py` — pure assembly, no DB/provider/authorization.

- Input: chatbot `system_prompt`, conversation history (`AIMessage` list), `RetrievedChunk` DTOs, latest user content.
- Output: `AIRequest` with `system_prompt` + `messages`.
- RAG context is injected as a **user message** containing a deterministic block:

```text
<knowledge_context>
[Source 1]
chunk content

[Source 2]
chunk content
</knowledge_context>
```

- Order in messages: history (including the latest user message, appearing exactly once) followed by the knowledge-context user message.
- System prompt: `chatbot.system_prompt` **always wins**; retrieved text is reference DATA, never higher-priority instruction, never replaces the system prompt. No RAG content stored as a Message; `chatbot.system_prompt` never modified.

### Prompt Injection Boundary

- Retrieved content is untrusted reference material, clearly delimited inside `<knowledge_context>` tags.
- Client can never inject `top_k`, RAG config, provider/model, or system prompt (request schema unchanged, `extra="forbid"`).

### Empty Retrieval

- 0 results is normal — generate from system prompt + history + user message; no fake context added.

### Retrieval Failure

- If retrieval fails: user message stays persisted, `AIGateway` is NOT called, no assistant message, safe 500-style error. No invented knowledge.

### Context Limits

- Centralized config: `rag_top_k` (default 5, max 20), `rag_max_context_chars` (default 8000). Client cannot set them in `/chat`. Token-aware budgeting is future.

### Per-Chatbot RAG Configuration

- `chatbots.rag_enabled` (boolean, NOT NULL, default `true`) and `chatbots.rag_top_k` (integer, nullable) let each chatbot enable/disable retrieval and override `top_k` without touching the global default.
- `rag_enabled=false`: `RetrievalService` is not called at all — not called-and-discarded. `ContextBuilder` receives an empty retrieved list and follows the existing "0 results" empty-retrieval path (system prompt + history + user message only, no fake context).
- `rag_top_k=NULL` (the default for existing and newly created chatbots — no backfill) means "use `settings.rag_top_k`"; the global constant remains the platform default. When set, it replaces `settings.rag_top_k` at the two call sites in `ChatRuntimeService` that previously used it unconditionally — `chat()` and `stream_turn()` (the latter shared by the authenticated chat path and the public widget path) — passed to both `RetrievalService.search()` and `ContextBuilder(top_k=...)`.
- Validation: `1 <= rag_top_k <= 20`, mirroring the existing bound on `KnowledgeSearchRequest.top_k` (`app/schemas/knowledge.py`) and this section's own documented default/max above — no new limit invented.
- The manual knowledge-search debug endpoint (`POST .../knowledge/search`, `KnowledgeSearchRequest.top_k`) is unaffected — it stays independent of per-chatbot RAG config.

### Citations & Sources

- Internal source metadata (`document_id`, `chunk_id`, `score`) retained in the knowledge context message for future citations; never expose vectors, DB internals, org data, or secrets.

### Tenant & Chatbot Isolation

- Retrieval uses server-controlled `organization_id` + `chatbot_id` from the conversation — cross-org/cross-chatbot knowledge can never be retrieved.

### Future

- Reranking, streaming, per-chatbot RAG config (enable/disable, top_k), token budgeting.

## 18. Real Embeddings & File Ingestion

### Embedding Providers

- Single `EmbeddingProvider` contract + single `EmbeddingRegistry`. Providers registered: `fake` (deterministic, offline, default) and `openai` (real HTTP, enabled only when `OPENAI_API_KEY` present).
- OpenAI provider: `httpx.AsyncClient` with explicit timeout, injectable for tests, batch `embed_texts`, vector parsing, **dimension validation** (mismatch → error; metadata and DB dimension must agree — 384).
- Provider selection via centralized config (`embedding_provider_id`); `RetrievalService` stays provider-agnostic.
- Errors normalized (auth/rate-limit/unavailable/timeout/malformed/dimension) — never leak keys, headers, raw responses, or stack traces.
- Fake provider remains for tests, offline dev, deterministic CI, no-key environments.

### File Ingestion

- Pipeline: `File → TextExtractor → Normalize → Chunk → Embed → Store`. Text ingestion shares the same normalize/chunk/embed/store pipeline.
- Supported: `.txt`, `.md`, `.pdf`, `.docx`. Rejected: xlsx/pptx/images/HTML/ZIP/executables.
- `DocumentTextExtractor`: bytes + filename → plain text. No DB/repo/auth/embed calls. Memory processing; never builds filesystem paths from raw filenames; no execution.
- Limits (centralized config): max file size 10 MB, max extracted text 100k chars, max name length.

### Document Lifecycle & Deduplication

- `pending → processing → ready`; failure `processing → failed`; never `ready` without valid chunks/vectors; no partial vector rows (failure marks failed).
- SHA-256 content hash (server-generated; client cannot spoof). Canonical input = normalized text.
- Duplicate rule: same org + same chatbot + same hash → 409; same content different chatbot/org → allowed.
- Re-ingestion: no versioning; re-uploading identical content to same chatbot → 409; changed content → new document.

### DB Changes

- `knowledge_documents` gains `original_filename`, `file_size`, `content_hash` (nullable for text ingestion without source file). Migration 0007.

### Security

- Uploaded files untrusted: extension + size + extracted-text validation; MIME not trusted alone; no paths from filenames; vectors/status/hash never client-controlled.

## 19. URL / Web Knowledge Ingestion

### Flow

```text
URL → URLValidator → SecureHTTPFetcher → HTMLTextExtractor → KnowledgeService → Normalize → Chunk → Embed → pgvector
```

- Reuses the existing ingestion pipeline (`_run_pipeline`) — no duplicate normalize/chunk/embed/hash/persist logic.
- Public pages only; no JS rendering, no crawler, no sitemaps, no authenticated sites, no cookies/custom headers.

### URL Validation (SSRF Protection)

- `URLValidator`: parse + normalize, scheme must be http/https, reject credentials, reject non-80/443 ports, resolve hostname, check **every** resolved IP against unsafe ranges (loopback, link-local, private IPv4/IPv6, multicast, unspecified, cloud metadata 169.254.169.254, `::1`, localhost), return canonical safe URL.
- Redirects never blindly followed: each hop re-validated (scheme/host/IP); max 5; public → private blocked.
- Not claimed as perfect SSRF defense (DNS rebinding window exists between validate and fetch); documented limitation.

### Fetching

- `httpx.AsyncClient`, explicit timeout (15s), injectable for tests, bounded redirects, response size limit 5 MB (stop reading on exceed), content-type must be `text/html` or `application/xhtml+xml`.
- User-agent from config (`PortableAI-KnowledgeBot/0.1`).
- Robots.txt: **respected** — fetch origin `robots.txt` through the same SSRF-safe fetcher; disallowed path → reject; if robots cannot be safely checked → fail closed.

### HTML Extraction & Canonical URL

- `HTMLTextExtractor` (beautifulsoup4): strip script/style/noscript/template/tags, decode entities, normalize whitespace; output feeds existing `TextNormalizer`.
- Canonical URL: lowercase scheme+host, strip default port, safe path normalization, keep meaningful query params.
- Extracted text limit reuses `max_extracted_text_chars`; oversized → reject (no truncation).

### Lifecycle & Dedup

- `source_type="url"`, canonical URL stored in `source_uri` (existing column — no migration).
- Reuse existing SHA-256 content hash + duplicate rules (same org+chatbot → 409; different chatbot/org allowed).
- Failure (DNS/conn/timeout/redirect/4xx/5xx/content-type/size/robots/empty HTML) → document `failed`, never searchable; safe generic errors, no internal network details.

### Future

- Crawler, sitemaps, background workers, JS rendering, per-source policies.

## 20. Streaming Chat (SSE)

### Transport

- SSE (Server-Sent Events) is the initial streaming transport; WebSocket is a future seam — the streaming abstraction is transport-agnostic so ChatRuntime/provider logic needs no rewrite.

### Normalized Streaming Contract

- `AIStreamEvent`: stable machine-readable `type` (`start`, `token`, `end`, `error`) + typed payload (content delta, finish_reason, usage, error detail, message ids).
- Provider raw chunks are converted to `AIStreamEvent` inside adapters; provider formats never escape.

### Provider Streaming Abstraction

- Providers expose `stream(request)` returning an async generator of `AIStreamEvent` (in addition to existing `generate`).
- `AIGateway.stream()` resolves provider/model (same validation as `generate`), requires `STREAMING` capability, and yields normalized events. No provider branching in the gateway.
- FakeAIProvider: deterministic word-by-word streaming (offline, no key).
- OpenAI-compatible provider: SSE from the provider API via `httpx.AsyncClient.stream`, converts deltas to token events, normalizes finish_reason, captures usage when available; raw responses never escape.

### Runtime Flow

```text
user message → authorization → persist user message → history → retrieval → ContextBuilder
→ AIGateway.stream → SSE token events → assemble final → persist ONE assistant message
```

- Streaming uses the same RAG pipeline and ContextBuilder as normal chat — no duplicate retrieval/context logic.
- Only the final assembled assistant response is persisted as one `Message` with the next server-controlled sequence; token chunks are never stored as messages.

### Persistence & Failure Semantics

- User message committed before streaming (existing strategy).
- If streaming fails mid-way: user message stays, incomplete assistant response is NOT persisted, SSE `error` event emitted when possible, safe generic detail only.
- On success: `end` event carries persisted assistant message info.

### Cancellation / Disconnect

- Client disconnect propagates cancellation into the provider stream (async generator `aclose`/`throw` path); the open `httpx` stream is closed, no orphaned tasks, DB session cleaned up by existing dependency teardown.
- Documented: cancellation stops provider consumption; incomplete output not persisted.

### Error Handling

- Provider exceptions reuse the existing AI error hierarchy; streaming errors become safe SSE `error` events (no stack traces, keys, headers, raw payloads, paths, DB details).
- If headers already sent, HTTP status cannot change — the error travels as an SSE event; pre-stream validation errors (auth, archived, invalid request) return normal HTTP statuses (401/403/404/409/422).

### Endpoint

- `POST /api/v1/organizations/{organization_id}/conversations/{conversation_id}/chat/stream` — same auth/tenant/membership rules as `POST /chat`; request schema unchanged (`content` only, `extra="forbid"`).
- SSE headers: `text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` (proxy buffering hint).

### Security

- Client cannot control provider/model/system prompt/sequence/role/RAG config; cross-tenant streams impossible (same authorization chain as normal chat); no secrets/credentials/raw provider data in any event.

## 21. Public Embeddable Widget

### Architecture

```text
Website → widget.js → Public Widget API → Widget Session → existing ChatRuntime
→ RetrievalService → ContextBuilder → AIGateway → SSE → widget
```

- Thin public boundary around the existing runtime. No duplicate chat/RAG/streaming/provider systems.
- Authenticated organization APIs remain unchanged and protected.

### Public Identity (public_key)

- Dedicated cryptographically-random, non-sequential `public_key` per chatbot (not derived from DB ids). Safe to expose publicly; rotatable/revocable via `revoked_at`.
- Stored in `widget_configs` table: `id`, `chatbot_id`, `public_key` (unique), `enabled`, `allowed_origins` (JSON list), `theme_color`/`widget_position`/`avatar_url` (all nullable — NULL means widget.js's built-in default, no backfill), timestamps, `revoked_at`.
- Never contains provider credentials, JWT secret, or DB credentials.

### Anonymous Visitor Session

- Widget visitors are anonymous; **no fake User accounts**. Widget sessions live in `widget_sessions` table: `id`, `chatbot_id`, `session_token` (random, unique, unguessable), `created_at`, `last_seen_at`, `expires_at`.
- Session bound to exactly one chatbot; server derives `organization_id`/`chatbot_id` from the widget config — client never supplies them.
- Session cannot be transferred between chatbots/organizations/conversations.

### Public Conversations

- Widget conversations reuse the existing `Conversation`/`Message` tables (single storage, no duplication).
- `user_id` stays NOT NULL: widget conversations reference a dedicated server-created **system/placeholder user** (one per organization, `is_active=false`, reserved email). Authenticated conversation security unchanged.

### Public API

- `POST /api/v1/public/widget/session` — `{public_key, origin}` → creates/returns session token + safe config.
- `GET /api/v1/public/widget/config` — `{public_key}` → theme/language only, no session created, no DB write; lets the always-visible launcher theme itself before the visitor ever interacts. Rate-limited via the same `widget_ip_rate_limiter` machinery as the chat endpoints.
- `POST /api/v1/public/widget/chat/stream` — `{session_token, content, origin}` → SSE stream reusing Step 15 runtime.
- Config response: `chatbot_name`, `welcome_message`, `language`, `enabled`, `theme_color`, `widget_position`, `avatar_url` only. **Never** system_prompt, provider_id, model_id, organization_id, DB ids, credentials.
- Public availability: chatbot must be `active` + `public`. draft/archived/private → 404 (no enumeration).

### Origin Control & CORS

- Server-side `Origin` header check against `allowed_origins` (empty list = no origins allowed; `["*"]` allowed only in explicit dev mode). Denied → 403.
- Public endpoints served without global CORS change; widget cross-origin handled by per-endpoint CORS headers.

### Rate Limiting (MVP)

- In-memory process-local limiter: per-session message count + per-IP window; max message length (existing 20000); session expiry (default 24h). Documented as process-local, not multi-instance production-safe.

### Widget Package

- `packages/widget/` — vanilla JS (no build step): loader, floating launcher, chat panel, message rendering (plain text, **no innerHTML with untrusted content**), input, SSE handling, error state, session persistence via localStorage (non-sensitive session token only), duplicate-init guard, mobile-friendly CSS.

### Widget Customization (Theme & Language)

- `theme_color` (hex, `^#[0-9a-fA-F]{6}$`, 6-digit only), `widget_position` (`bottom_right`/`bottom_left` only), `avatar_url` live on `widget_configs`, nullable, NULL = widget.js's current built-in defaults (hardcoded blue, bottom-right, no avatar). One theme per chatbot — `WidgetConfig` stays effectively 1:1 with `Chatbot`, as it is today; no multiple themed embeds per chatbot.
- Avatar is an **uploaded image**, not a freeform admin-entered URL: `POST /api/v1/organizations/{organization_id}/chatbots/{chatbot_id}/widget-config/avatar` (authenticated, organization-scoped, admin+), multipart file upload. Validated by actual file content (magic bytes), not extension or client-supplied `Content-Type` — PNG/JPEG/WebP only, max ~1MB. Stored on local disk under a dedicated, gitignored, configurable upload directory; filename is a generated UUID + validated extension, never the client's original filename. Served via a static route that validates the requested path stays within the upload directory (no traversal). Re-uploading replaces the previous file (old file deleted, not orphaned) and updates `avatar_url` to the new served path. Rendered client-side only (`<img src="...">` in the visitor's browser) — the backend never re-fetches it, so there is no SSRF surface.
- `language` reuses the existing `chatbots.language` field (already the widget response's only consumer); `widget.js` gains a small built-in `en`/`ur` string table for its own chrome text, selected by the returned `language`, falling back to `en`. `ur` additionally sets `dir="rtl"` on the chat panel — a real layout change, not just translated strings.
- `GET /api/v1/public/widget/config` is fetched eagerly at script load (no session, no DB write) so the always-visible launcher renders themed from the start; the existing lazy session-creation flow on first message is unchanged.
- `WidgetConfigService.update()` + `PATCH .../widget-config` (admin, organization-scoped) is new — no update path existed before this milestone.

### XSS Protection

- All model output/user content/welcome message rendered as text via `textContent` — never `innerHTML` with untrusted data. No eval, no dynamic script execution.

## 22. API Versioning

- All endpoints under `/api/v1/` — e.g. `/api/v1/health`, `/api/v1/auth/...`, `/api/v1/organizations/...`, `/api/v1/chatbots/...`.
- Version router mounted at `/api/v1` in `main.py`.
- Breaking changes go to `/api/v2/` with deprecation policy (TBD).

## 23. Security

- bcrypt password hashing.
- JWT access tokens (short-lived); no refresh tokens yet.
- Tenant isolation at data layer; never trust client-supplied tenant IDs.
- Secrets only via environment variables (`pydantic-settings`); `.env` gitignored.
- CORS restricted to configured origins.
- Input validation via Pydantic schemas.
- Health endpoint never exposes database credentials, URLs, or connection strings.
- Generic auth failures (401) — never reveal whether email exists or password was wrong.

## 24. Application Layout

```text
apps/api/app/
├── main.py                    # app factory, middleware, / and /widget.js routes
├── core/
│   ├── config.py              # pydantic-settings Settings (env-driven, prod fail-fast)
│   ├── database.py            # async engine, session factory, Base, get_db()
│   ├── security.py            # JWT create/decode, bcrypt hash/verify
│   ├── dependencies.py        # get_current_user, membership/role dependencies
│   ├── logging.py             # structured logging + redaction
│   ├── middleware.py          # error handling, request logging, body-size limit
│   └── rate_limit.py          # RateLimiter abstraction + in-memory widget limiters
├── api/v1/
│   ├── router.py              # aggregates v1 routers
│   ├── health.py              # /health (liveness), /ready (readiness)
│   ├── auth.py                # register, login, me
│   ├── organizations.py       # create, list
│   ├── chatbots.py            # chatbot CRUD + lifecycle + widget-config management
│   ├── conversations.py       # conversations, messages, chat + chat/stream (SSE)
│   ├── knowledge.py           # text/file/url ingestion, search, documents
│   ├── ai_management.py       # read-only provider/model discovery
│   └── public_widget.py       # public session + SSE chat stream
├── ai/                        # provider-agnostic AI gateway
│   ├── contracts.py           # AIRequest/AIResponse/AIMessage/AIUsage
│   ├── capabilities.py        # capability enum
│   ├── metadata.py            # ProviderMetadata/ModelMetadata
│   ├── exceptions.py          # provider-neutral error hierarchy
│   ├── provider_registry.py   # ProviderRegistry
│   ├── model_registry.py      # ModelRegistry
│   ├── gateway.py             # AIGateway (generate/stream)
│   ├── streaming.py           # AIStreamEvent contract
│   ├── registry.py            # default registries + fake registration
│   └── providers/
│       ├── base.py            # AIProvider protocol, OpenAICompatibleProvider base
│       ├── fake.py            # FakeAIProvider (deterministic, offline)
│       └── openai_compatible.py  # real OpenAI-compatible HTTP adapter
├── rag/                       # knowledge pipeline + embeddings
│   ├── normalizer.py          # TextNormalizer
│   ├── chunker.py             # Chunker
│   ├── embeddings.py          # EmbeddingProvider contract
│   ├── fake_embeddings.py     # deterministic offline embeddings
│   ├── openai_embeddings.py   # real OpenAI-compatible embeddings
│   ├── registry.py            # EmbeddingRegistry
│   ├── text_extractor.py      # txt/md/pdf/docx extraction
│   ├── html_extractor.py      # HTML→text (beautifulsoup4)
│   ├── http_fetcher.py        # SSRF-safe fetcher
│   └── url_validator.py       # SSRF-safe URL validation
├── models/                    # 10 SQLAlchemy models (users … widget_sessions)
├── schemas/                   # Pydantic DTOs
├── repositories/              # tenant-scoped data access
└── services/                  # business logic (auth, organization, chatbot, widget_config,
                               # conversation, message, knowledge, retrieval, context_builder,
                               # chat_runtime, public_widget, ai_management)
```

## 25. Testing Strategy

- **Unit/API tests** (default `pytest`): fast, no external services. Covers `GET /`, `GET /api/v1/health`, auth flows, organization flows, tenant isolation.
- **Integration/DB tests** (`pytest -m integration`): require the project's Docker PostgreSQL. Covers session creation, `SELECT 1`, pgvector extension presence, migration apply/downgrade/re-apply. They use `AsyncSessionLocal` against the Docker instance — never a random local PostgreSQL.
- API tests for auth/organizations use a dedicated test database session against the Docker PostgreSQL (test data isolated via unique emails/slugs; no production data touched).
- DB tests are marked `integration` so the default run stays fast and dependency-free.
- Prerequisite for integration tests: `docker compose up -d postgres` and a valid `.env`.

### Continuous Integration

GitHub Actions (`.github/workflows/ci.yml`) is the project quality gate and runs on every push to `main` and on all pull requests. All jobs are blocking — failures must not be silenced. Two independent jobs:

- **frontend** (Ubuntu, Node 22): `npm ci` → `npm run test` (Vitest) → `npm run build`, executed from `apps/frontend`.
- **backend** (Ubuntu, Python 3.11): installs `requirements.txt`, provisions a service container mirroring the dev database (`pgvector/pgvector:pg16`, database/user/password `portableai`), applies schema via `alembic upgrade head`, then runs the full `pytest` suite (unit + identity + integration) from `apps/api`. `DATABASE_URL` and the development `JWT_SECRET` are provided as workflow-level environment values — no real secrets live in the repository or workflow.

CI therefore enforces the same verification commands developers run locally; it never skips DB-backed tests and never uses `continue-on-error`.

## 26. Out of Scope (current milestone)

WebSocket transport, widget per-install customization beyond the current public config, recursive crawling/sitemaps/JS rendering/OCR, background workers, reranking, semantic cache, document versioning, automatic re-indexing, more embedding providers, analytics, agents, MCP, idempotency keys, usage persistence, fallback/circuit breaker (transient-failure retry-with-backoff is implemented — see §13's "Transient Provider Error Retry"), provider/model DB tables, provider enable/disable mutation, platform-admin role.

## 27. Future AI Gateway Extensions

Foundation implemented (`app/ai/`, `app/rag/`, SSE streaming, public widget). Future additions on top:

- `services/agents/` — orchestration on gateway + RAG.
- Vision/multimodal, more providers.
- Chatbot entity stays provider-agnostic; provider choice is a runtime config concern.

## 28. Explicitly Out of Scope

OAuth, Google/GitHub login, email verification, MFA, more real providers, credential management UI, LangChain, LlamaIndex, agents, integrations. (Password reset and refresh tokens shipped — see 'Refresh Token Rotation & Password Reset' below.)

## 29. Production Hardening

### Environment & Configuration

- `ENVIRONMENT` setting (`development` | `test` | `production`), default `development`.
- Fail-fast on startup in `production`: `JWT_SECRET` must be a strong value (the documented dev default is rejected), and all required secrets/URLs must be present. Development keeps safe defaults for convenience.
- CORS origins, trusted hosts, log level, and request limits all come from environment.

### Trusted Hosts

- `TRUSTED_HOSTS` is a **JSON array** (e.g. `["portableai.example.com"]`) from env, parsed by pydantic-settings into `list[str]`; enforced via `TrustedHostMiddleware` when non-empty. Empty = allow all (development convenience; production validation requires a non-empty value). Prevents Host-header injection.

### Centralized Error Handling

- Global exception handlers return safe JSON error DTOs (`{"detail": ...}`) — no stack traces, no provider internals, no DB details, no secrets.
- Unhandled exceptions are logged server-side (with traceback for debugging in dev) and returned as a generic safe 500 in production.
- SSE streams already normalize provider failures to safe `error` events (Step 20).

### Request Body Limits

- Global JSON body size cap enforced by middleware (`max_request_bytes`, default 1 MB) → 413.
- Existing per-feature limits remain: message content ≤ 20000 chars, file ≤ 10 MB, URL response ≤ 5 MB, extracted text ≤ 100k chars, RAG context ≤ 8000 chars, streaming assembled response unconstrained.

### Health & Readiness

- `GET /api/v1/health` — lightweight liveness: process up. No DB dependency.
- `GET /api/v1/ready` — readiness: performs `SELECT 1` against PostgreSQL. Returns 200 when DB reachable, 503 otherwise. Never exposes DB URL/credentials.

### Logging

- Structured application logging (`app/core/logging.py`) with a consistent format.
- A request-logging middleware records method, path, status, and duration.
- **Never logged**: API keys, JWTs, passwords, authorization headers, provider credentials, full prompts. Redaction applied to any error-logged content.
- Health/ready probes are excluded from request logs to reduce noise.

### Rate Limiting Abstraction

- `app/core/rate_limit.py` defines a `RateLimiter` backend protocol with an in-memory sliding-window implementation (default) and a Redis-backed implementation, selected via `settings.rate_limiter_backend` (`"memory"` | `"redis"`, default `"memory"`) — routes depend on the abstraction, not the concrete limiter, so the existing 4 call sites needed zero changes.
- Widget endpoints use per-session (30/hr) and per-IP (1000/hr) limiters created through a factory. Password-reset request endpoints use the same factory (5/hr per-email, 20/hr per-IP).
- Redis backend: fixed-window `INCR key` + `EXPIRE key window_seconds` (set only on the first hit in a window) — matches the coarse abuse-prevention precision the existing limiters actually need, not a sorted-set sliding window. Uses a single shared, module-level `redis.ConnectionPool` with a synchronous `redis.Redis` client per limiter instance — synchronous because the `RateLimiter.allow()` protocol (and its 4 existing call sites) is synchronous, and changing that was out of scope for this milestone.
- Fail-open: if Redis is unreachable, `allow()` logs at WARNING and returns `True` rather than rejecting the request or raising — a Redis outage degrades to "no rate limiting," never to an unrelated endpoint returning 500 or 429.
- Local dev/test default stays the in-memory backend (matching this project's established "fake/local by default, real backend opt-in" convention) — Redis-backed tests are `@pytest.mark.integration`, run against a `redis:7-alpine` service container in both local docker-compose and CI, mirroring the existing Postgres integration-test pattern exactly.

### Authentication Hardening

- JWT access tokens: `sub`, `exp`, `type`; expiration enforced by PyJWT; `type == "access"` required by decode.
- Generic 401 on all auth failures — no user enumeration.
- `get_current_user` always reloads the user from DB and checks `is_active` — JWT alone grants nothing.
- Password hashing via bcrypt (direct); min length 8 enforced at schema.

### Refresh Token Rotation & Password Reset

```text
POST /api/v1/auth/refresh                    (cookie in, cookie+access token out)
POST /api/v1/auth/logout                     (revokes current refresh-token family)
POST /api/v1/auth/password-reset/request      {"email": str}
POST /api/v1/auth/password-reset/confirm      {"token": str, "new_password": str}
```

- `refresh_tokens`: `id`, `user_id` (FK, CASCADE), `family_id` (indexed), `token_hash` (SHA-256, unique — never stored plaintext, deliberately stricter than `widget_sessions.session_token`'s plaintext storage, since a refresh token grants full account access), `issued_at`, `expires_at`, `revoked_at` (nullable).
- Rotation: every `/auth/refresh` call issues a new access token and a new refresh token, revokes the presented one, and the new row inherits the same `family_id`. Presenting an already-revoked token is treated as theft — the entire family is revoked and the caller must re-authenticate.
- Cookie: `HttpOnly; Secure; SameSite=None; Path=/api/v1/auth`. `SameSite=None` specifically because the frontend supports a cross-origin deployment topology (`VITE_API_BASE_URL` pointing at a separate backend service); `allow_credentials=True` is already set on `CORSMiddleware` with an explicit origin allowlist (never `"*"`), which is what makes a credentialed cross-origin cookie legal here.
- Widget sessions (`widget_sessions.session_token`) are a completely separate mechanism — passed explicitly in request bodies, never a cookie — and are unaffected by this change.
- `password_reset_tokens`: `id`, `user_id` (FK, CASCADE), `token_hash` (SHA-256, unique), `expires_at` (1 hour), `used_at` (nullable), `created_at`. `/password-reset/request` always returns the same generic response regardless of whether the email exists (matches the existing login enumeration-safety pattern). A successful `/password-reset/confirm` also revokes all of that user's `refresh_tokens` families.
- Email delivery is real, via Resend's REST API (`app/services/email.py`): a hand-built `httpx` call (matching the OpenAI-compatible provider adapter's pattern — no `resend` SDK dependency, the send-email endpoint is a single trivial JSON POST) to `POST https://api.resend.com/emails` with `Authorization: Bearer {settings.resend_api_key}`, sender `settings.email_from_address` (defaults to Resend's shared test address `onboarding@resend.dev`, swappable to a verified custom domain via config alone). `RESEND_API_KEY` is required in production (`fail_fast_production` refuses to start otherwise) but empty by default — when empty, `send_password_reset_email` falls back to logging the reset URL (with the raw, unhashed token) at INFO instead of sending, the same deliberate, temporary exception to the "never log bearer credentials" policy the original stub documented; this fallback path is structurally unreachable in production, since the app cannot start there without a key. Every existing safety property is unchanged: `request_password_reset()` still returns identically whether or not the account exists, and now also identically whether or not the email actually sends — `send_password_reset_email` never raises (any Resend failure is caught, logged server-side without the API key or raw token, and reported back only as `False`), so a provider outage degrades to "no email sent," never to a different response shape or a leaked error detail. Rate limiting (`password_reset_email_rate_limiter`, `password_reset_ip_rate_limiter`) is unaffected — it still gates the request before `AuthService.request_password_reset()` is ever called.

### Authorization Audit (Step 17)

Reviewed every protected route:

- **Organizations**: membership required for every org-scoped route; role checks via `require_organization_role`.
- **Chatbots**: `get_by_id_for_organization` everywhere; create/update/activate/archive/delete require admin+; list/read require member+.
- **Conversations/messages**: member reads own only, owner/admin read all; archive of others requires owner/admin; all queries org-scoped.
- **Chat runtime (normal + streaming)**: same authz chain as conversations; archived → 409; cross-org denied.
- **Knowledge**: org+chatbot scoped; member+; cross-org returns nothing/404.
- **AI management**: authenticated read-only discovery; no credentials/base URLs returned.
- **Public widget**: separate public boundary — `public_key` identity, origin control, session binding; never trusts client-supplied org/chatbot/provider/model/system_prompt.

### Health of Existing Systems

No rewrites: auth, JWT, orgs, memberships, chatbot CRUD, AI gateway, registries, conversations, messages, ChatRuntimeService, RAG, embeddings, ingestion, SSE, public widget — all unchanged and backward compatible.

## 30. Frontend / Admin Dashboard

### Location & Stack

- `apps/frontend/` — React + TypeScript + Vite.
- Minimal dependencies: `react`, `react-dom`, `react-router-dom`, `vite`, `@vitejs/plugin-react`, TypeScript. No state library (React context), no UI framework — small hand-rolled CSS. No duplicate backend logic — the frontend is a thin API consumer.
- Dev-only test tooling: Vitest + React Testing Library + `@testing-library/jest-dom` + `@testing-library/user-event` + jsdom. Tests run via `npm run test` (`vitest run`) and are excluded from the production build.

### Architecture

The frontend currently uses a **flat `pages/` layout**. Feature-folder
decomposition is NOT implemented and remains only a future refactor seam.

```text
apps/frontend/src/
├── api/            # client.ts + types.ts: the frontend/backend contract mirror
│                   #   (typed fetch wrapper, Bearer injection, ApiError, SSE streamChat)
├── auth/           # AuthContext: login/register/logout, token hydration via /auth/me
├── components/     # shared UI (RequireAuth)
├── layout/         # AppLayout (sidebar shell + Outlet)
├── pages/          # one file per screen (flat): Login, Register, Dashboard,
│                   #   Organizations, Chatbots, ChatbotDetail (nested tabs:
│                   #   Chat console / Knowledge / Widget), WidgetPreview, Providers
├── App.tsx         # router + AuthProvider (protected/guest routes)
├── main.tsx        # React root
└── styles.css      # global hand-rolled CSS
```

- Route definitions live inline in `App.tsx`; protected routes render under
  `<RequireAuth><AppLayout/></RequireAuth>`.
- `api/types.ts` mirrors the backend Pydantic DTOs field-for-field; provider/model
  metadata is fetched from the live AI management API, never hardcoded.
- Auth state is React Context only; there is no global state-management library.

### Testing

- Vitest with the jsdom environment, configured in `vite.config.ts` (`test` section).
- Setup file wires `@testing-library/jest-dom/vitest` matchers; tests mock `fetch`
  at the global boundary — no real backend calls.
- Coverage targets the contract seams: `api/client.ts` (headers, error
  normalization, 401 token clearing) and `auth/AuthContext.tsx` (hydration,
  login, logout, invalid-token cleanup); plus `streamChat()` SSE parsing
  (chunk buffering, malformed-frame tolerance, `[DONE]`-less protocol,
  abort propagation); and page flows for `WidgetConfigPage`
  (load/create/revoke, embed snippet generation, preview route link),
  `KnowledgePage` (text/URL/file ingestion, search, deletion, refresh)
  and `ChatConsolePage` (conversation selection/creation, message
  history, optimistic send + SSE reconciliation).

### API Client

- `api/client.ts` — single fetch wrapper: injects `Authorization: Bearer` from the auth context, parses JSON, normalizes errors into a typed `ApiError` with status + safe detail.
- `api/types.ts` — TypeScript mirrors of the backend DTOs (Pydantic schemas). Provider/model lists come from the live AI management API — never hardcoded.

### Auth Flow

- Login/Register POST to `/api/v1/auth/*`; token stored in `localStorage` (`portableai_access_token`).
- Auth context exposes `user`, `token`, `login`, `register`, `logout`.
- Protected routes redirect to `/login` when unauthenticated; guest routes redirect away when authenticated.
- Logout clears token and redirects. API 401 responses trigger a session-expiry redirect.

### Chat Console

- Reuses the existing `POST .../chat/stream` SSE endpoint via `fetch` + `ReadableStream` parsing — no second chat runtime.
- Renders `user` / `start` / `token` / `end` / `error` events; shows loading state; renders RAG-backed responses exactly as delivered.
- Conversation create/select + message history come from existing endpoints.

### Widget Configuration UI

- Reads/writes the existing `widget-config` management endpoints (create, get, revoke).
- Shows `public_key` (safe public identifier), enabled state, allowed origins.
- Generates the embed snippet pointing at the configured API origin + `/widget.js`.
- **Preview**: an isolated iframe on the same origin loads the real `widget.js` with the widget's `public_key` — reuses the actual widget implementation (no fake preview), origin-limited, no session tokens exposed.

### Security

- Token stored client-side (standard SPA pattern); documented trade-off — no refresh tokens, so token expiry logs the user out.
- Never renders untrusted content via `innerHTML`; assistant output rendered as text.
- No backend credentials, provider keys, or base URLs are fetched or bundled.

## 31. Deployment

### Containers

- `apps/api/Dockerfile` — backend image: Python 3.11-slim, installs requirements, runs uvicorn as a non-root user. Bundles `packages/widget/widget.js` (provided as the `widget` build context by compose) so the API serves the public widget script from the image.
- `apps/frontend/Dockerfile` — multi-stage: Node build → nginx serving the static bundle.
- `infrastructure/docker-compose.prod.yml` — `postgres`, `api`, `api-migrate`, `frontend` (nginx reverse proxy: serves SPA, proxies `/api` and `/widget.js` to the API).
- Persistent PostgreSQL volume; healthchecks on postgres and api.

### Configuration

- All secrets via environment: `JWT_SECRET`, `DATABASE_URL`, `OPENAI_API_KEY` (optional), `EMBEDDING_PROVIDER_ID`, etc.
- `.env.example` provides safe placeholders; real `.env` files are gitignored and never committed.
- The `api` and `api-migrate` services share the same production environment (`JWT_SECRET`, `CORS_ORIGINS`, `TRUSTED_HOSTS`, `DATABASE_URL`): alembic's `env.py` imports `app.core.config`, whose production validation fails fast without those variables.

### Migration Procedure

- Migrations run via the one-shot `api-migrate` service (`docker compose -f infrastructure/docker-compose.prod.yml run --rm api-migrate`), which executes `alembic upgrade head` against PostgreSQL before the API starts. Migrations are idempotent/versioned; the `api` container runs uvicorn only.

### Reverse Proxy

- nginx (frontend container) is the only public entry point; API is not directly exposed to the internet in the prod compose.
- SSE requires `proxy_buffering off` for the streaming endpoints — configured in nginx.

## 32. Roadmap

- Steps 1–16 = **completed** (MVP backend foundation → database → identity → chatbot CRUD → AI gateway → conversations/messages → chat runtime → real provider → provider/model management → RAG foundation → RAG runtime integration → real embeddings → file ingestion → URL ingestion → streaming SSE → public widget).
- Step 17 = **completed** (production hardening + frontend/admin dashboard + deployment).
- Future: WebSocket transport, OAuth/refresh tokens, retries/circuit breakers, reranking/hybrid search, background workers, per-chatbot RAG config, billing, analytics, agents, MCP, platform-admin, Redis-backed rate limiting, widget customization, more providers.
