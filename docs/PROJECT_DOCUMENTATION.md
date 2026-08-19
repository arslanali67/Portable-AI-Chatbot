# PortableAI — Historical Project Technical Documentation (Steps 1–6)

*Detailed implementation documentation for Steps 1–6 — kept for reference only.*

> **HISTORICAL.** This document describes only the Step 1–6 foundation and is **superseded** by the current architecture in `src/backend/architecture.md` and the project rules in `src/PROJECT_RULES.md`. The MVP is complete — see those files (and `README.md`) for the current system, which adds AI/RAG, real providers, embeddings, streaming, the public widget, and production hardening on top of the Steps 1–6 base described here.

---

## Section 1 — Project Overview

### What PortableAI is

PortableAI is a **multi-tenant, customizable AI chatbot platform**. The current codebase is a backend foundation (Steps 1–6): a FastAPI application with PostgreSQL persistence, a complete identity system, organization-owned chatbots, an AI gateway abstraction with fake (offline) providers, and persistent conversation/message history.

**Implemented Steps 1–6**

| Step | What was built |
| --- | --- |
| 1 | FastAPI application foundation, `/` and `/api/v1/health` endpoints |
| 2 | PostgreSQL + pgvector, SQLAlchemy 2.x async, Alembic migrations |
| 3 | Users, Organizations, Memberships, JWT auth, bcrypt hashing, RBAC, tenant isolation |
| 4 | Chatbot CRUD + configuration, lifecycle (draft/active/archived), RBAC, tenant isolation |
| 5 | AI Gateway: provider/model abstraction, registries, capabilities, normalized request/response, fake providers, chatbot `provider_id`/`model_id` |
| 6 | Conversations + Messages (persistent chat history), ordering, pagination, tenant isolation, conversation lifecycle |

### High-level architecture

```text
User
 ↓
Membership
 ↓
Organization
 ↓
Chatbot
 ↓
Conversation
 ↓
Messages
```

And the AI path (foundation only — no real provider calls):

```text
Chatbot
 ↓
AI Gateway
 ↓
Provider abstraction
 ↓
Provider
```

**Layer explanations**

- **User** — an account with email + bcrypt-hashed password. Can belong to many organizations.
- **Membership** — join row linking a user to an organization with a role (`owner`, `admin`, `member`).
- **Organization** — the tenant boundary. All tenant-scoped data hangs off it.
- **Chatbot** — an organization-owned chatbot configuration (name, slug, system prompt, provider/model selection, status, visibility).
- **Conversation** — a chat session under one chatbot, created by one user, owned by the organization.
- **Message** — immutable text history inside a conversation, ordered by `sequence_number`.
- **AI Gateway** — provider-agnostic orchestration: validates request, resolves provider/model from registries, checks capabilities, calls a provider adapter, normalizes the response.

---

## Section 2 — Source of Truth

`src/` is the **architectural source of truth**. Before any code change the developer must read the architecture documents and, if the architecture changes, update `src/` first.

Key documents:

- `src/PROJECT_RULES.md` — project rules, technology stack, database rules, current scope.
- `src/backend/architecture.md` — backend architecture: layering, multi-tenancy, identity system, chatbot architecture, conversation & message architecture, AI gateway architecture, migrations policy, testing strategy.

From `src/PROJECT_RULES.md`:

> `src/` is the architectural source of truth.
> Before any feature is implemented, it must first be defined in architecture documents under `src/`.

Working rule: **architecture decision first, implementation second.**

---

## Section 3 — Complete Project Tree

Actual repository tree (only existing files/directories):

```text
Portable AI Chatbot/
├── AI chatbot/                     # existing Python virtual environment
├── apps/
│   └── api/
│       ├── app/
│       │   ├── main.py
│       │   ├── ai/
│       │   │   ├── __init__.py
│       │   │   ├── capabilities.py
│       │   │   ├── contracts.py
│       │   │   ├── exceptions.py
│       │   │   ├── gateway.py
│       │   │   ├── metadata.py
│       │   │   ├── model_registry.py
│       │   │   ├── provider_registry.py
│       │   │   ├── registry.py
│       │   │   └── providers/
│       │   │       ├── __init__.py
│       │   │       ├── base.py
│       │   │       └── fake.py
│       │   ├── api/
│       │   │   └── v1/
│       │   │       ├── auth.py
│       │   │       ├── chatbots.py
│       │   │       ├── conversations.py
│       │   │       ├── health.py
│       │   │       ├── organizations.py
│       │   │       └── router.py
│       │   ├── core/
│       │   │   ├── config.py
│       │   │   ├── database.py
│       │   │   ├── dependencies.py
│       │   │   ├── logging.py
│       │   │   └── security.py
│       │   ├── models/
│       │   │   ├── __init__.py
│       │   │   ├── base.py
│       │   │   ├── chatbot.py
│       │   │   ├── conversation.py
│       │   │   ├── enums.py
│       │   │   ├── membership.py
│       │   │   ├── message.py
│       │   │   ├── organization.py
│       │   │   └── user.py
│       │   ├── repositories/
│       │   │   ├── chatbot.py
│       │   │   ├── conversation.py
│       │   │   ├── membership.py
│       │   │   ├── message.py
│       │   │   ├── organization.py
│       │   │   └── user.py
│       │   ├── schemas/
│       │   │   ├── auth.py
│       │   │   ├── chatbot.py
│       │   │   ├── conversation.py
│       │   │   ├── organization.py
│       │   │   └── user.py
│       │   └── services/
│       │       ├── auth.py
│       │       ├── chatbot.py
│       │       ├── conversation.py
│       │       ├── message.py
│       │       └── organization.py
│       ├── alembic/
│       │   ├── env.py
│       │   ├── script.py.mako
│       │   └── versions/
│       │       ├── .gitkeep
│       │       ├── 0001_enable_pgvector.py
│       │       ├── 0002_create_identity_tables.py
│       │       ├── 0003_create_chatbots.py
│       │       ├── 0004_add_chatbot_ai_configuration.py
│       │       └── 0005_create_conversations_messages.py
│       ├── tests/
│       │   ├── conftest.py
│       │   ├── test_ai_gateway.py
│       │   ├── test_chatbots.py
│       │   ├── test_conversations.py
│       │   ├── test_database.py
│       │   ├── test_health.py
│       │   └── test_identity.py
│       ├── .env.example
│       ├── .gitignore
│       ├── alembic.ini
│       ├── pytest.ini
│       └── requirements.txt
├── docs/
│   └── .gitkeep
├── infrastructure/
│   ├── .gitkeep
│   └── docker-compose.yml
├── packages/
│   └── .gitkeep
├── src/
│   ├── PROJECT_RULES.md
│   └── backend/
│       └── architecture.md
├── tests/
│   └── .gitkeep
├── PROJECT_RULES.md
└── README.md
```

**Top-level directories**

| Directory | Purpose |
| --- | --- |
| `apps/api/` | The FastAPI backend (modular monolith) |
| `src/` | Architectural source of truth (docs) |
| `infrastructure/` | Docker Compose for dev PostgreSQL + pgvector |
| `docs/` | Product/technical docs |
| `packages/`, `tests/` | Placeholders for future shared packages / cross-app tests |

---

## Section 4 — File-by-File Documentation

### `apps/api/app/main.py`

- **Purpose**: FastAPI application entry point.
- **Why**: creates the ASGI app, wires CORS, mounts routers, exposes the root metadata endpoint.
- **Important**: `app` (FastAPI instance), `root()` endpoint.
- **Dependencies**: `app.api.v1.router.api_router`, `app.core.config.settings`, `app.core.logging.setup_logging`.
- **Architecture role**: composition root — everything connects here.
- **What breaks if removed**: no HTTP server.

```python
# Simplified
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router, prefix=settings.api_v1_prefix)
```

### `apps/api/app/core/config.py`

- **Purpose**: typed application settings via `pydantic-settings`.
- **Why**: single configuration source; secrets come from environment / `.env`.
- **Important**: `Settings`, `get_settings()`, `settings` singleton.
- **Note**: `jwt_secret` and `database_url` are required (`Field(...)`); the app refuses to start without them.

### `apps/api/app/core/database.py`

- **Purpose**: centralized async SQLAlchemy foundation.
- **Why**: one engine + one session factory; repositories/services/routes never create engines.
- **Important**: `engine`, `AsyncSessionLocal`, `Base`, `get_db()`.

```python
# Simplified
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

### `apps/api/app/core/security.py`

- **Purpose**: bcrypt password hashing + JWT creation/validation.
- **Important**: `hash_password()`, `verify_password()`, `create_access_token()`, `decode_access_token()`.
- **No secrets here**: secret comes from settings.

### `apps/api/app/core/dependencies.py`

- **Purpose**: shared FastAPI dependencies: authentication + authorization.
- **Important**: `get_current_user()`, `require_organization_membership()`, `require_organization_role()`.

### `apps/api/app/core/logging.py`

- **Purpose**: root logging configuration.
- **Important**: `setup_logging()`, `get_logger()`.

### `apps/api/app/api/v1/router.py`

- **Purpose**: aggregates all v1 routers.
- **Important**: `api_router` includes health, auth, organizations, chatbots, conversations routers.

### `apps/api/app/api/v1/*.py` (auth, organizations, chatbots, conversations, health)

- **Purpose**: HTTP layer only — parse requests, call services, map errors to HTTP.
- **Important endpoints**: see Section 10.

### `apps/api/app/models/*.py`

- **Purpose**: SQLAlchemy 2.x typed ORM models (`User`, `Organization`, `Membership`, `Chatbot`, `Conversation`, `Message`), plus `Base` re-export and `TimestampMixin` in `base.py`, and `enums.py`.
- **Important**: every tenant-scoped model carries `organization_id`; enum values stored lowercase via `values_callable`.

### `apps/api/app/schemas/*.py`

- **Purpose**: Pydantic request/response DTOs.
- **Important**: `extra="forbid"` on create/update schemas (unknown fields → 422); response models never expose `password_hash`.

### `apps/api/app/repositories/*.py`

- **Purpose**: data access. Tenant-scoped methods (`get_by_id_for_organization`, `list_for_organization`) — no unsafe global `get_by_id()` for tenant-owned resources.

### `apps/api/app/services/*.py`

- **Purpose**: business logic (validation, lifecycle, ownership, transactions).

### `apps/api/app/ai/*.py`

- **Purpose**: provider-agnostic AI gateway foundation. See Section 15.

### `apps/api/alembic/versions/*.py`

- **Purpose**: schema migrations 0001–0005. See Section 24.

### `apps/api/tests/*.py`

- **Purpose**: test suite. See Section 28.

---

## Section 5 — FastAPI

`apps/api/app/main.py`:

- **App creation**: `FastAPI(title=settings.app_name, version=settings.app_version, debug=settings.debug, docs_url="/docs", openapi_url="/openapi.json")`.
- **Middleware**: `CORSMiddleware` with `allow_origins` from settings, `allow_credentials=True`, all methods/headers.
- **Router registration**: `app.include_router(api_router, prefix=settings.api_v1_prefix)` where `api_router` aggregates all v1 routers.
- **Startup/shutdown**: none defined (no lifespan hooks currently).
- **Configuration**: read from `app.core.config.settings`.
- **Health endpoints**:

| Method | Path | Response |
| --- | --- | --- |
| GET | `/` | `{"name": "PortableAI API", "version": "0.1.0", "status": "running"}` |
| GET | `/api/v1/health` | `{"status": "ok", "service": "portableai-api"}` |

- **Request flow**: HTTP client → uvicorn → FastAPI app → `/api/v1` router → endpoint handler → service → repository → SQLAlchemy async → PostgreSQL.

---

## Section 6 — Configuration

`apps/api/app/core/config.py` uses `pydantic-settings`:

| Setting | Env var | Default | Notes |
| --- | --- | --- | --- |
| `app_name` | `APP_NAME` | `PortableAI API` | |
| `app_version` | `APP_VERSION` | `0.1.0` | |
| `debug` | `DEBUG` | `false` | |
| `api_v1_prefix` | `API_V1_PREFIX` | `/api/v1` | |
| `jwt_secret` | `JWT_SECRET` | **required** | never commit real value |
| `jwt_algorithm` | `JWT_ALGORITHM` | `HS256` | |
| `access_token_expire_minutes` | `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | |
| `database_url` | `DATABASE_URL` | **required** | asyncpg URL |
| `redis_url` | `REDIS_URL` | `redis://localhost:6379/0` | not used yet |
| `cors_origins` | `CORS_ORIGINS` | `["http://localhost:3000"]` | |
| `log_level` | `LOG_LEVEL` | `INFO` | |

- Config loads from `.env` (gitignored) or environment variables.
- Required fields (`jwt_secret`, `database_url`) fail fast at import if missing.
- No real secrets in source; dev values live only in `.env` / `.env.example`.

---

## Section 7 — Database

`apps/api/app/core/database.py`:

- **Async engine**: `create_async_engine(settings.database_url, pool_pre_ping=True)`.
- **Session factory**: `AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False)`.
- **Base**: `class Base(DeclarativeBase)` — parent for all ORM models.
- **Dependency**: `get_db()` yields a request-scoped `AsyncSession` and closes it on teardown.

```text
API
 ↓
get_db()
 ↓
AsyncSession
 ↓
Repository
 ↓
PostgreSQL
```

- Transactions are committed by services (`await session.commit()`), with `rollback()` on `IntegrityError`.
- One central engine; no engine-per-request, no engines inside repositories/services/routes.

---

## Section 8 — Security

`apps/api/app/core/security.py`:

- **bcrypt hashing**: `hash_password(password)` → `bcrypt.hashpw(password.encode(), bcrypt.gensalt())`. `verify_password(password, password_hash)` → `bcrypt.checkpw`.
- **JWT creation**: `create_access_token(user_id)` builds claims `{"sub": str(user_id), "exp": <utc now + minutes>, "type": "access"}` and signs with `jwt_secret`/`jwt_algorithm` (HS256).
- **JWT validation**: `decode_access_token(token)` decodes with the same algorithm; raises `jwt.PyJWTError` on failure.
- **Authentication = who are you?** — `get_current_user()` validates the Bearer JWT, loads the user from the database, checks `is_active`.
- **Authorization = what can you do?** — `require_organization_role()` checks membership role rank.
- **Tenant isolation = which organization's data can you access?** — repository queries always scoped by `organization_id`.

Only `password_hash` is stored; plaintext passwords never persisted or returned.

---

## Section 9 — Dependencies / Authorization

`apps/api/app/core/dependencies.py`:

| Function | Purpose |
| --- | --- |
| `get_current_user()` | Bearer JWT → decode → load user from DB → check active → return `User`; 401 on missing/invalid/unknown/inactive |
| `require_organization_membership(organization_id)` | org exists (404) + user is member (403) |
| `require_organization_role(required_role)` | factory returning a dependency; membership + role rank check; member(1) < admin(2) < owner(3) |

Authorization flow for organization-scoped resources: authenticated → organization exists → user member → role sufficient → resource belongs to that organization. Client-supplied ids are never trusted on their own.

---

## Section 10 — API Routes

All under `/api/v1`. Every endpoint actually registered (from `router.py` + routers).

### Health (`api/v1/health.py`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | none | liveness; returns `{"status": "ok", "service": "portableai-api"}` |

### Meta (`main.py`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/` | none | service info; returns `{"name": "PortableAI API", "version": "0.1.0", "status": "running"}` |

### Auth (`api/v1/auth.py`)

| Method | Path | Auth | Purpose | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| POST | `/api/v1/auth/register` | none | create account | `{"email", "password", "full_name"}` | 201 `UserResponse` (no password/hash) | 409 duplicate email; 422 validation |
| POST | `/api/v1/auth/login` | none | OAuth2 form login | form `username`, `password` | 200 `{"access_token", "token_type": "bearer"}` | 401 bad credentials (generic) |
| GET | `/api/v1/auth/me` | Bearer | current user | — | 200 `UserResponse` | 401 |

### Organizations (`api/v1/organizations.py`)

| Method | Path | Auth | Purpose | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| POST | `/api/v1/organizations` | Bearer | create org + owner membership (transactional) | `{"name", "slug"}` | 201 `OrganizationResponse` | 409 duplicate slug |
| GET | `/api/v1/organizations` | Bearer | list orgs user belongs to | — | 200 list `OrganizationResponse` | 401 |

### Chatbots (`api/v1/chatbots.py`)

| Method | Path | Auth/Role | Purpose | Response | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/api/v1/organizations/{oid}/chatbots` | admin+ | create chatbot (status forced `draft`) | 201 `ChatbotResponse` | 409 slug taken |
| GET | `/api/v1/organizations/{oid}/chatbots` | member+ | list org chatbots | 200 list | 403 not member |
| GET | `/api/v1/organizations/{oid}/chatbots/{cid}` | member+ | get chatbot | 200 | 404 |
| PATCH | `/api/v1/organizations/{oid}/chatbots/{cid}` | admin+ | partial config update | 200 | 404, 409 slug, 422 |
| POST | `/api/v1/organizations/{oid}/chatbots/{cid}/activate` | admin+ | `draft → active` | 200 | 404, 409 transition |
| POST | `/api/v1/organizations/{oid}/chatbots/{cid}/archive` | admin+ | `draft/active → archived` | 200 | 404, 409 transition |
| DELETE | `/api/v1/organizations/{oid}/chatbots/{cid}` | admin+ | hard delete (MVP) | 204 | 404 |

### Conversations (`api/v1/conversations.py`)

| Method | Path | Auth/Role | Purpose | Response | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/api/v1/organizations/{oid}/chatbots/{cid}/conversations` | member+ | create conversation | 201 | 404 chatbot |
| GET | `/api/v1/organizations/{oid}/chatbots/{cid}/conversations` | member+ | list (member: own; owner/admin: all) | 200 `ConversationListResponse` | 403 |
| GET | `/api/v1/organizations/{oid}/conversations/{conv_id}` | member+ | get conversation | 200 | 404, 403 |
| POST | `/api/v1/organizations/{oid}/conversations/{conv_id}/messages` | member+ | create user message | 201 | 404, 403, 409 archived/sequence |
| GET | `/api/v1/organizations/{oid}/conversations/{conv_id}/messages` | member+ | list messages (seq ASC, limit/offset) | 200 `MessageListResponse` | 404, 403 |
| POST | `/api/v1/organizations/{oid}/conversations/{conv_id}/archive` | member+ (owner/admin any; member own) | `active → archived` | 200 | 404, 403, 409 |

No PATCH/DELETE endpoints exist for messages (immutable) and no DELETE for conversations.

---

## Section 11 — Database Models

All models use SQLAlchemy 2.x typed style (`Mapped[...]` / `mapped_column`), integer autoincrement PKs, and lowercase enum values stored via `values_callable`.

```text
User
 ↓
Membership
 ↓
Organization
 ↓
Chatbot
 ↓
Conversation
 ↓
Message
```

### User — `users`

| Column | Type | Constraints |
| --- | --- | --- |
| id | Integer | PK |
| email | String(255) | unique (`uq_users_email`), indexed |
| password_hash | String(255) | not null |
| full_name | String(255) | not null |
| is_active | Boolean | default true |
| created_at / updated_at | DateTime(timezone) | server default now() |

Relationships: `memberships` (cascade delete-orphan), `conversations`.

### Organization — `organizations`

| Column | Type | Constraints |
| --- | --- | --- |
| id | Integer | PK |
| name | String(255) | not null |
| slug | String(100) | unique (`uq_organizations_slug`), indexed |
| created_at / updated_at | DateTime(timezone) | |

Relationships: `memberships`, `chatbots`, `conversations`. **This is the tenant entity.**

### Membership — `memberships`

| Column | Type | Constraints |
| --- | --- | --- |
| id | Integer | PK |
| user_id | Integer FK → users.id | CASCADE, indexed |
| organization_id | Integer FK → organizations.id | CASCADE, indexed |
| role | enum `membership_role` (owner/admin/member) | default member |
| created_at / updated_at | DateTime(timezone) | |

Unique `(user_id, organization_id)` (`uq_membership_user_organization`). Enforces 1 user → many orgs, 1 org → many users.

### Chatbot — `chatbots`

| Column | Type | Constraints |
| --- | --- | --- |
| id | Integer | PK |
| organization_id | Integer FK → organizations.id | CASCADE, indexed |
| name | String(255) | not null |
| slug | String(100) | unique per org (`uq_chatbots_organization_slug`) |
| description / system_prompt / welcome_message | Text | default "" |
| status | enum `chatbot_status` (draft/active/archived) | default draft |
| visibility | enum `chatbot_visibility` (private/public) | default private |
| language | String(10) | default `en` |
| provider_id / model_id | String(100) | defaults `fake-a` / `fake-model-small` |
| created_at / updated_at | DateTime(timezone) | |

Relationships: `organization`, `conversations`.

### Conversation — `conversations`

| Column | Type | Constraints |
| --- | --- | --- |
| id | Integer | PK |
| organization_id | Integer FK → organizations.id | RESTRICT, indexed |
| chatbot_id | Integer FK → chatbots.id | RESTRICT, indexed |
| user_id | Integer FK → users.id | RESTRICT, indexed |
| title | String(255) | not null |
| status | enum `conversation_status` (active/archived) | default active |
| created_at / updated_at | DateTime(timezone) | |

Relationships: `organization`, `chatbot`, `user`, `messages` (cascade delete-orphan). Explicit `organization_id` makes tenant-scoped queries safe even when chatbot id is known.

### Message — `messages`

| Column | Type | Constraints |
| --- | --- | --- |
| id | Integer | PK |
| conversation_id | Integer FK → conversations.id | CASCADE, indexed |
| role | enum `message_role` (system/user/assistant) | not null |
| content | Text | not null |
| sequence_number | Integer | unique per conversation (`uq_message_conversation_sequence`) |
| metadata | JSON | nullable (mapped as `metadata_json` — `metadata` is reserved on Declarative) |
| created_at | DateTime(timezone) | |

No `updated_at` — messages are immutable. Relationship: `conversation`.

### Enums (`models/enums.py`)

`MembershipRole` (owner/admin/member), `ChatbotStatus` (draft/active/archived), `ChatbotVisibility` (private/public), `ConversationStatus` (active/archived), `MessageRole` (system/user/assistant).

### Base / mixin

`models/base.py` re-exports `Base` and defines `TimestampMixin` (`created_at`/`updated_at`). Individual models declare columns explicitly (mixin not applied everywhere).

---

## Section 12 — Pydantic Schemas

### Auth (`schemas/auth.py`)

- `RegisterRequest`: `email` (EmailStr), `password` (8–128), `full_name` (1–255).
- `TokenResponse`: `access_token`, `token_type="bearer"`.
- `RegisterResponse` extends `UserResponse` — safe user data only.

### User (`schemas/user.py`)

- `UserResponse`: id, email, full_name, is_active, created_at. **Never contains password_hash.**

### Organization (`schemas/organization.py`)

- `OrganizationCreate`: `name` (1–255), `slug` (pattern `^[a-z0-9]+(?:-[a-z0-9]+)*$`).
- `OrganizationResponse`: id, name, slug, created_at (`from_attributes=True`).
- `MembershipResponse`: id, organization_id, role, created_at.

### Chatbot (`schemas/chatbot.py`)

- `ChatbotCreate` with `extra="forbid"`: name, slug (slug pattern), description, system_prompt, welcome_message, language (must be in `{"en", "ur"}`), visibility (enum), `provider_id`/`model_id` (pattern `^[a-zA-Z0-9._-]+$`, defaults `fake-a`/`fake-model-small`). **No status field — server forces `draft`.**
- `ChatbotUpdate` with `extra="forbid"`: all optional, partial update. **Immutable fields (`id`, `organization_id`, timestamps) have no field — sending them → 422.**
- `ChatbotResponse`: full config incl. provider_id/model_id.

### Conversation & Message (`schemas/conversation.py`)

- `ConversationCreate` with `extra="forbid"`: only `title`. Client cannot set organization/chatbot/user/status.
- `ConversationResponse`: id, organization_id, chatbot_id, user_id, title, status, timestamps.
- `ConversationListResponse`: `{items, total, limit, offset}`.
- `MessageCreate` with `extra="forbid"`: only `content` (+ optional `metadata`). **Client cannot set role, sequence_number, conversation_id, organization_id — 422 if attempted.**
- `MessageResponse`: id, conversation_id, role, content, sequence_number, metadata, created_at. `metadata` maps from model `metadata_json` via `validation_alias`.
- `MessageListResponse`: `{items, total, limit, offset}`.

`MAX_LIST_LIMIT = 200`, `DEFAULT_LIST_LIMIT = 50` — used by services to clamp pagination.

---

## Section 13 — Repositories

Layering: **API → Service → Repository → Database.**

| Repository | Key methods | Tenant safety |
| --- | --- | --- |
| `UserRepository` | `get`, `get_by_email`, `create` | global identity (not tenant-scoped) |
| `OrganizationRepository` | `get`, `get_by_slug`, `create`, `list_for_user` (join membership) | org list scoped by user membership |
| `MembershipRepository` | `get(user_id, org_id)`, `create` | pair-scoped |
| `ChatbotRepository` | `create`, `get_by_id_for_organization`, `list_for_organization`, `get_by_slug_for_organization`, `delete` | every query includes `organization_id` |
| `ConversationRepository` | `create`, `get_by_id_for_organization`, `list_for_organization` (count + page) | every query includes `organization_id` |
| `MessageRepository` | `create`, `get_latest_sequence`, `list_for_conversation` | scoped through conversation id (conversation itself org-scoped) |

Real snippet (chatbot repo — org scope in every query):

```python
# Simplified
async def get_by_id_for_organization(self, organization_id: int, chatbot_id: int):
    result = await self.db.execute(
        select(Chatbot).where(
            Chatbot.id == chatbot_id, Chatbot.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()
```

There is intentionally **no** global `get_by_id()` on tenant-owned repositories.

---

## Section 14 — Services

| Service | Responsibilities | Errors |
| --- | --- | --- |
| `AuthService` | register (normalize email, hash password, check duplicate), authenticate (generic failure), issue token | `DuplicateEmailError`, `InvalidCredentialsError` |
| `OrganizationService` | create org + owner membership transactionally, list user orgs | `DuplicateSlugError` |
| `ChatbotService` | create (slug check), get/list (org-scoped), update (partial, slug check), lifecycle transitions, delete | `ChatbotNotFoundError`, `DuplicateSlugError`, `InvalidStatusTransitionError` |
| `ConversationService` | create (chatbot must belong to org), get, list (member scoping), archive (owner/admin any, member own) | `ChatbotNotFoundError`, `ConversationNotFoundError`, `ArchivePermissionError`, `InvalidArchiveError` |
| `MessageService` | create user message (status check, next sequence, immutable), list (paginated) | `ConversationNotFoundError`, `ConversationArchivedError`, `SequenceConflictError` |

Real snippet (message sequence assignment):

```python
# Simplified
sequence = (await self.messages.get_latest_sequence(conversation_id)) + 1
message = await self.messages.create(
    conversation_id=conversation_id,
    role=MessageRole.USER,
    content=payload.content,
    sequence_number=sequence,
    metadata=payload.metadata,
)
```

---

## Section 15 — AI Gateway

### Files in `apps/api/app/ai/`

| File | Contents |
| --- | --- |
| `contracts.py` | `AIMessage`, `AIUsage`, `AIRequest`, `AIResponse` (frozen dataclasses) |
| `capabilities.py` | `AICapability` enum |
| `metadata.py` | `ProviderMetadata`, `ModelMetadata`, `AuthenticationType`, `CompatibilityType` |
| `exceptions.py` | `AIError` hierarchy |
| `provider_registry.py` | `ProviderRegistry`, `DuplicateProviderError` |
| `model_registry.py` | `ModelRegistry`, `DuplicateModelError` |
| `gateway.py` | `AIGateway` |
| `registry.py` | default registries + `gateway` singleton + chatbot defaults |
| `providers/base.py` | `AIProvider` Protocol, `OpenAICompatibleProvider` base |
| `providers/fake.py` | `FakeAIProvider` |

### Contracts

```python
# Simplified (frozen dataclasses)
@dataclass(frozen=True)
class AIRequest:
    provider_id: str
    model_id: str
    messages: list[AIMessage]
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class AIResponse:
    content: str
    provider_id: str
    model_id: str
    finish_reason: str
    usage: AIUsage
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Capabilities

`AICapability`: `TEXT_GENERATION`, `STREAMING`, `TOOL_CALLING`, `STRUCTURED_OUTPUT`, `VISION`, `AUDIO_INPUT`, `AUDIO_OUTPUT`, `EMBEDDINGS`, `IMAGE_GENERATION`, `JSON_MODE`, `REASONING`. Only `TEXT_GENERATION` is exercised by the fake provider path; the rest exist for capability checks.

### Metadata

- `ProviderMetadata`: provider_id, display_name, description, enabled, base_url, authentication_type, compatibility_type, capabilities. **Never stores API secrets.**
- `ModelMetadata`: provider_id, model_id, display_name, context_window, max_output_tokens, enabled, capabilities.

### Registries

- `ProviderRegistry`: `register` (duplicate → error), `get` (unknown → `AIProviderUnavailableError`), `list`, `exists`.
- `ModelRegistry`: `register` (duplicate → error), `get(provider_id, model_id)`, `list(provider_id)`, `exists`. Keys are `(provider_id, model_id)` tuples — no model enum.

### AIGateway flow

```text
AIRequest
 ↓
AIGateway
 ↓
ProviderRegistry
 ↓
ModelRegistry
 ↓
Capability checks
 ↓
Provider
 ↓
AIResponse
```

`AIGateway.generate()`: validate request → resolve provider → provider enabled → resolve model → model enabled + belongs to provider → required capability present → call provider adapter → return normalized `AIResponse`. Unknown adapter exceptions are wrapped in `AIProviderError`.

**Provider-agnostic**: the gateway never branches on provider ids (`if provider == "openai"` does not exist). Adding a provider = adapter + metadata + models + registration + tests; adding a model = metadata + registration. No core changes, no migration.

### Error hierarchy (`exceptions.py`)

`AIError` → `AIProviderError` → `AIAuthenticationError`, `AIRateLimitError`, `AIInvalidRequestError`, `AIModelNotFoundError`, `AIProviderUnavailableError`; plus `AICapabilityNotSupportedError`.

### OpenAI-compatible abstraction

`OpenAICompatibleProvider` base class in `providers/base.py` — placeholder base for future OpenAI/Kimi/DeepSeek/Qwen/Groq/custom endpoints. Subclasses implement `generate`.

---

## Section 16 — Fake Providers

`apps/api/app/ai/providers/fake.py` — `FakeAIProvider`:

- Deterministic, offline, no API key, no network.
- Response mirrors the last user message: `"[{label}] {message}"`.
- Registered providers in `registry.py`: `fake-a` (label `provider-a`) and `fake-b` (label `provider-b`).
- Registered models: `fake-model-small` (4k context), `fake-model-large` (32k context) under `fake-a`; `fake-model-small` under `fake-b`.
- Value: unit-test friendly; proves multi-provider switching requires no gateway changes; development works without external services.

```python
# Simplified
class FakeAIProvider:
    async def generate(self, request: AIRequest) -> AIResponse:
        last_user = next((m.content for m in reversed(request.messages) if m.role.value == "user"), "")
        content = f"[{self.label}] {last_user}"
        return AIResponse(content=content, provider_id=request.provider_id,
                          model_id=request.model_id, finish_reason="stop",
                          usage=AIUsage(input_tokens=10, output_tokens=len(content.split())))
```

---

## Section 17 — Chatbot AI Config

- Chatbot stores `provider_id` and `model_id` as plain strings (columns added by migration `0004`).
- **Why separate**: one provider can serve many models; ids are extensible strings, not enums.
- **Storage**: `chatbots.provider_id` (default `fake-a`), `chatbots.model_id` (default `fake-model-small`).
- **Validation**: Pydantic pattern `^[a-zA-Z0-9._-]+$`, length 1–100 on create/update.
- **Defaults**: defined in `app/ai/registry.py` (`DEFAULT_PROVIDER_ID = "fake-a"`, `DEFAULT_MODEL_ID = "fake-model-small"`) and mirrored as DB/server defaults — never hardcoded in services/routes/gateway.
- **Future extensibility**: new model = metadata + registration only (no migration); new provider = adapter + metadata + models + registration.

---

## Section 18 — Conversations

`Conversation` model + `ConversationService` + `conversations.py` router.

- **Organization ownership**: explicit `organization_id` FK (RESTRICT) — conversation can never cross org boundary.
- **Chatbot relationship**: `chatbot_id` FK (RESTRICT); service verifies chatbot belongs to the organization before creating.
- **User ownership**: `user_id` FK (RESTRICT) = authenticated creator.
- **Title**: required, 1–255 chars.
- **Status**: `active` (default) / `archived`.
- **Timestamps**: created_at/updated_at.
- **Archive behavior**: `active → archived`; archived conversations remain readable but reject new messages (409). No restore endpoint. No DELETE endpoint.

---

## Section 19 — Messages

`Message` model + `MessageService` + message endpoints in `conversations.py`.

- **conversation_id**: FK (CASCADE), indexed — messages deleted with conversation.
- **role**: enum — `system`, `user`, `assistant`. **Client may only create `user`**; `role`/`sequence_number`/`conversation_id` in the request → 422 (`extra="forbid"`).
- **content**: Text, required (1–20000 chars in schema).
- **sequence_number**: server-assigned integer, unique per conversation.
- **metadata**: optional JSON; `MessageResponse` maps model `metadata_json` → `metadata`.
- **created_at**: server default; **no updated_at** — messages are immutable (no PATCH/DELETE endpoints).

---

## Section 20 — Message Ordering

Ordering is by `sequence_number`, never timestamps alone.

```text
1 → message 1
2 → message 2
3 → message 3
```

- Server assigns `latest + 1` inside the service (`MessageService.create_user_message`).
- `UNIQUE(conversation_id, sequence_number)` (`uq_message_conversation_sequence`) prevents duplicates.
- **Concurrency**: on a race, PostgreSQL raises IntegrityError → service maps it to `SequenceConflictError` → 409. Documented MVP approach; an atomic counter/row-lock is a future refinement.
- Listing returns `sequence_number ASC`.

---

## Section 21 — Conversation Lifecycle

```text
active
 ↓
archived
```

- Only transition: `active → archived` (POST archive).
- Archived conversation: still readable (GET works), **rejects new messages** (409 "Conversation is archived").
- No restore, no permanent delete endpoint (history kept for future analytics/RAG/debugging/audit).

---

## Section 22 — Tenant Isolation

```text
User A → Org A → Bot A → Conversation A → Message A
User B → Org B → Bot B → Conversation B → Message B
```

Cross-tenant access is prevented at three layers:

1. **Dependencies**: `require_organization_role(MembershipRole.MEMBER)` — user must be a member of the org in the path; else 403.
2. **Repositories**: every tenant query includes `organization_id` (e.g. `get_by_id_for_organization(organization_id, ...)`).
3. **Services**: ownership verification — conversation creation checks `chatbot.get_by_id_for_organization(org_id, chatbot_id)`; messages require the conversation via org-scoped lookup.

Real dependency snippet:

```python
# Simplified
async def require_organization_role(required_role):
    async def dependency(organization_id, user=Depends(get_current_user), db=Depends(get_db)):
        organization = await OrganizationRepository(db).get(organization_id)
        if organization is None:
            raise HTTPException(404, "Organization not found")
        membership = await MembershipRepository(db).get(user.id, organization_id)
        if membership is None:
            raise HTTPException(403, "Not a member of this organization")
        if _ROLE_RANK.get(membership.role, 0) < _ROLE_RANK[required_role]:
            raise HTTPException(403, "Insufficient role for this organization")
        return membership
    return dependency
```

**Why unscoped `get_by_id()` is dangerous**: a query keyed only by resource id ignores the tenant column; an attacker who guesses another org's resource id could read it. Every tenant-owned repository therefore exposes only org-scoped lookups — `message_id` alone never grants access.

---

## Section 23 — RBAC

Roles: `owner`, `admin`, `member` (rank 3 > 2 > 1). Actual behavior:

| Resource / action | owner | admin | member |
| --- | --- | --- | --- |
| Create organization | yes (creator becomes owner) | — | — |
| List orgs | own memberships | own memberships | own memberships |
| Create chatbot | yes | yes | **403** |
| Read chatbot | yes | yes | yes |
| Update/activate/archive/delete chatbot | yes | yes | **403** |
| Create conversation | yes | yes | yes (own) |
| List conversations | all org | all org | own only |
| Read conversation | all org | all org | own only (else 403) |
| Create message | own + any org conversation (admin/owner) | same | own conversations only |
| Read messages | all org | all org | own conversations only |
| Archive conversation | any org | any org | own only (else 403) |

Conversation read policy: member → own conversations; owner/admin → all organization conversations (enforced in `ConversationService.list` and the router's member-scope check).

---

## Section 24 — Migrations

Why Alembic: schema changes go only through migrations; app code never creates/alters tables; `env.py` reads `DATABASE_URL` from settings and targets `Base.metadata`; no credentials in `alembic.ini`.

| Migration | Purpose | Tables / changes | Notes |
| --- | --- | --- | --- |
| `0001_enable_pgvector.py` | enable pgvector extension | `CREATE EXTENSION IF NOT EXISTS vector` (downgrade drops it) | no vector columns yet |
| `0002_create_identity_tables.py` | identity tables | `users`, `organizations`, `memberships`; enum `membership_role`; unique email, slug, `(user_id, organization_id)`; indexes | |
| `0003_create_chatbots.py` | chatbot config | `chatbots`; enums `chatbot_status`, `chatbot_visibility`; unique `(organization_id, slug)` | |
| `0004_add_chatbot_ai_configuration.py` | AI config | adds `provider_id` (default `fake-a`), `model_id` (default `fake-model-small`) to `chatbots` | no enums — extensible ids |
| `0005_create_conversations_messages.py` | chat history | `conversations` (FKs org/chatbot/user RESTRICT), `messages` (FK conversation CASCADE); enums `conversation_status`, `message_role`; unique `(conversation_id, sequence_number)` | RESTRICT protects history from accidental org/chatbot deletion |

Head: `0005`.

---

## Section 25 — PostgreSQL / Docker

`infrastructure/docker-compose.yml`:

| Item | Value |
| --- | --- |
| Image | `pgvector/pgvector:pg16` |
| Container | `portableai-postgres` |
| Database | `portableai` |
| User | `portableai` |
| Password | dev value in compose file (not a real secret) |
| Port | `5432:5432` |
| Volume | `postgres_data:/var/lib/postgresql/data` |
| Healthcheck | `pg_isready -U portableai -d portableai`, 5s interval |

**Why pgvector exists**: RAG is **NOT implemented** (future). The extension is enabled now (migration 0001) so the schema is ready; vector operations will go through a future abstraction.

---

## Section 26 — Environment

`apps/api/.env.example` variables (values redacted/development only):

```text
APP_NAME=PortableAI API
APP_VERSION=0.1.0
DEBUG=false
LOG_LEVEL=INFO
JWT_SECRET=<redacted>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
DATABASE_URL=<redacted>   # postgresql+asyncpg://user:pass@localhost:5432/portableai
REDIS_URL=redis://localhost:6379/0
CORS_ORIGINS=["http://localhost:3000"]
```

- `.env` is gitignored; `.env.example` is the template.
- `JWT_SECRET` and `DATABASE_URL` are required; real values never committed.

---

## Section 27 — Dependencies

`apps/api/requirements.txt` (no versions pinned):

| Package | Purpose |
| --- | --- |
| `fastapi` | web framework |
| `uvicorn[standard]` | ASGI server |
| `pydantic`, `pydantic-settings` | validation + config |
| `sqlalchemy` | ORM |
| `psycopg[binary]`, `asyncpg` | PostgreSQL drivers (async) |
| `alembic` | migrations |
| `python-dotenv` | .env loading |
| `python-multipart` | OAuth2 form login |
| `PyJWT` | JWT tokens |
| `bcrypt` | password hashing (direct; passlib dropped — incompatible with bcrypt 5.x) |
| `email-validator` | EmailStr validation |
| `redis` | future cache/queue (not used yet) |
| `httpx` | HTTP client (future gateway calls) |
| `pytest`, `pytest-asyncio` | testing |

---

## Section 28 — Test Architecture

`apps/api/tests/`:

| File | Purpose | DB |
| --- | --- | --- |
| `conftest.py` | NullPool test engine + `get_db` dependency override (Windows event-loop safety) | Docker PostgreSQL |
| `test_health.py` | `GET /`, `GET /api/v1/health` (2 tests) | none |
| `test_database.py` | session creation, `SELECT 1`, reachability, pgvector extension (marked `integration`, 4 tests) | Docker |
| `test_identity.py` | auth flows, organizations, roles, tenant isolation (marked `identity`, 17 tests) | Docker |
| `test_chatbots.py` | chatbot CRUD, tenant isolation, roles, validation, lifecycle, AI config (marked `identity`, 28 tests) | Docker |
| `test_conversations.py` | conversations/messages, ordering, pagination, roles, tenant isolation (marked `identity`, 26 tests) | Docker |
| `test_ai_gateway.py` | pure unit: registries, gateway, capabilities, errors, multi-provider, Kimi/future-model extensibility (20 tests) | none |

Markers in `pytest.ini`: `integration` and `identity` (both require Docker PostgreSQL + migrations applied). `asyncio_default_test_loop_scope = session`.

---

## Section 29 — Test Results

Actual run (local Docker PostgreSQL running, migrations at head 0005):

```text
97 passed, 1 warning in 105.23s
```

The single warning is an upstream `StarletteDeprecationWarning` about `httpx` in `TestClient` (install `httpx2` instead) — non-blocking.

What the suite verifies: root/health endpoints, DB foundation + pgvector, full identity/org/auth flows, chatbot CRUD + RBAC + lifecycle + tenant isolation, conversations/messages + ordering + pagination + immutability + tenant isolation, AI gateway registries/capabilities/errors/multi-provider/extensibility.

---

## Section 30 — API Reference

| Method | Path | Auth | Purpose | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/` | — | service info | — | `{name, version, status}` | — |
| GET | `/api/v1/health` | — | liveness | — | `{status, service}` | — |
| POST | `/api/v1/auth/register` | — | create user | `{email, password, full_name}` | 201 user | 409, 422 |
| POST | `/api/v1/auth/login` | — | OAuth2 form login | form `username`/`password` | 200 token | 401 |
| GET | `/api/v1/auth/me` | Bearer | current user | — | 200 user | 401 |
| POST | `/api/v1/organizations` | Bearer | create org + owner | `{name, slug}` | 201 org | 409, 422 |
| GET | `/api/v1/organizations` | Bearer | list user orgs | — | 200 list | 401 |
| POST | `/api/v1/organizations/{oid}/chatbots` | admin+ | create chatbot | config payload | 201 | 403, 409, 422 |
| GET | `/api/v1/organizations/{oid}/chatbots` | member+ | list | — | 200 list | 403 |
| GET | `/api/v1/organizations/{oid}/chatbots/{cid}` | member+ | get | — | 200 | 403, 404 |
| PATCH | `/api/v1/organizations/{oid}/chatbots/{cid}` | admin+ | partial update | optional config fields | 200 | 403, 404, 409, 422 |
| POST | `/api/v1/organizations/{oid}/chatbots/{cid}/activate` | admin+ | draft→active | — | 200 | 403, 404, 409 |
| POST | `/api/v1/organizations/{oid}/chatbots/{cid}/archive` | admin+ | →archived | — | 200 | 403, 404, 409 |
| DELETE | `/api/v1/organizations/{oid}/chatbots/{cid}` | admin+ | hard delete | — | 204 | 403, 404 |
| POST | `/api/v1/organizations/{oid}/chatbots/{cid}/conversations` | member+ | create conversation | `{title}` | 201 | 403, 404, 422 |
| GET | `/api/v1/organizations/{oid}/chatbots/{cid}/conversations` | member+ | list (paginated) | `limit`/`offset` | 200 list | 403 |
| GET | `/api/v1/organizations/{oid}/conversations/{conv_id}` | member+ | get conversation | — | 200 | 403, 404 |
| POST | `/api/v1/organizations/{oid}/conversations/{conv_id}/messages` | member+ | create user message | `{content}` | 201 | 403, 404, 409, 422 |
| GET | `/api/v1/organizations/{oid}/conversations/{conv_id}/messages` | member+ | list (seq ASC) | `limit`/`offset` | 200 list | 403, 404 |
| POST | `/api/v1/organizations/{oid}/conversations/{conv_id}/archive` | member+ (own) / owner-admin | archive | — | 200 | 403, 404, 409 |

---

## Section 31 — End-to-End Flows

### Flow 1 — Register

```text
Client → POST /api/v1/auth/register → auth.py router → AuthService.register
→ UserRepository.get_by_email (duplicate check) → hash_password → create user → commit → DB
```

Then login issues a JWT: `POST /api/v1/auth/login` → `AuthService.authenticate` (verify_password) → `issue_token` → `create_access_token(user.id)`.

### Flow 2 — Create Organization

```text
User → POST /api/v1/organizations (Bearer) → get_current_user
→ OrganizationService.create → flush org → create owner membership → commit (transactional) → DB
```

### Flow 3 — Create Chatbot

```text
User → POST /organizations/{oid}/chatbots (Bearer) → require_organization_role(ADMIN)
→ ChatbotService.create (slug check, org scope) → ChatbotRepository.create → commit → DB
```

### Flow 4 — AI Gateway

```text
AIRequest → AIGateway.generate → ProviderRegistry.get(provider_id) → ModelRegistry.get
→ enablement + capability checks → provider.generate(request) → AIResponse
```

### Flow 5 — Create Conversation

```text
User → POST /organizations/{oid}/chatbots/{cid}/conversations (Bearer) → membership dep
→ ConversationService.create → ChatbotRepository.get_by_id_for_organization(oid, cid) (ownership)
→ create conversation (org, chatbot, user, title) → commit → DB
```

### Flow 6 — Create Message

```text
User → POST /organizations/{oid}/conversations/{conv_id}/messages (Bearer) → membership dep
→ conversation org-scoped lookup → member-ownership check → MessageService.create_user_message
→ status check (active) → next sequence (latest+1) → create (role=user) → commit → DB
```

---

## Section 32 — Error Handling

HTTP statuses actually used:

| Status | Meaning | Where |
| --- | --- | --- |
| 401 | unauthenticated / invalid token / bad credentials | auth, `get_current_user` |
| 403 | authenticated but forbidden (not member / wrong role / not your conversation) | org/chatbot/conversation routes |
| 404 | resource not found (org/chatbot/conversation) | chatbot, conversation routes |
| 409 | duplicate email/slug, invalid lifecycle transition, archived conversation, sequence conflict | auth, org, chatbot, conversation routes |
| 422 | Pydantic validation (incl. unknown fields via `extra="forbid"`) | all create/update routes |

AI exceptions (defined, raised inside the gateway/registries — no HTTP route uses them yet):

`AIError` → `AIProviderError` → `AIAuthenticationError`, `AIRateLimitError`, `AIInvalidRequestError`, `AIModelNotFoundError`, `AIProviderUnavailableError`; plus `AICapabilityNotSupportedError`. Also `DuplicateProviderError` / `DuplicateModelError` for registries.

---

## Section 33 — Security

| Control | Implementation |
| --- | --- |
| Password hashing | bcrypt via `hash_password`/`verify_password`; only `password_hash` stored |
| JWT | signed HS256, claims `sub`/`exp`/`type`, secret from env |
| Environment secrets | `JWT_SECRET` required, `.env` gitignored |
| RBAC | `require_organization_role` with role rank |
| Tenant isolation | org-scoped repository queries + membership deps |
| Password protection | never returned in any response schema |
| Provider credentials | **not implemented** — no API keys stored anywhere; metadata explicitly excludes secrets |
| Error normalization | gateway wraps unknown adapter exceptions in `AIProviderError`; login uses generic 401 |
| Logging safety | no sensitive prompt/credential logging configured; health endpoint exposes no credentials |

---

## Section 34 — Database Overview

```text
users ──< memberships >── organizations ──< chatbots ──< conversations ──< messages
 │                             │              │                │
 │                             │              │                └── conversation_id FK (CASCADE)
 │                             │              └── organization_id FK (CASCADE)
 │                             └── user_id FK / org_id FK / chatbot_id FK (RESTRICT)
 └── conversations.user_id FK (RESTRICT)
```

Key FKs:

- `memberships.user_id → users.id`, `memberships.organization_id → organizations.id`
- `chatbots.organization_id → organizations.id`
- `conversations.organization_id → organizations.id` (RESTRICT), `chatbots.id` (RESTRICT), `users.id` (RESTRICT)
- `messages.conversation_id → conversations.id` (CASCADE)

---

## Section 35 — Architecture Summary

```text
FastAPI API
 ↓
Dependencies/Auth (get_current_user, require_organization_role)
 ↓
Services (business logic)
 ↓
Repositories (org-scoped data access)
 ↓
SQLAlchemy (async ORM)
 ↓
PostgreSQL
```

And the AI path:

```text
Chatbot (provider_id/model_id)
 ↓
AI Gateway (AIGateway)
 ↓
Provider abstraction (AIProvider / OpenAICompatibleProvider)
 ↓
Provider (fake-a / fake-b today; future Kimi/DeepSeek/etc.)
```

Connection: chatbots reference providers/models by string ids; the gateway resolves them through the registries. The runtime loop (user message → gateway → assistant message) is **NOT connected yet** — Step 6 ends at `User Message → Database`.

---

## Section 36 — Implemented vs Future

| Feature | Status |
| --- | --- |
| FastAPI foundation | Implemented |
| PostgreSQL | Implemented |
| pgvector extension | Implemented (no columns) |
| SQLAlchemy 2.x async | Implemented |
| Alembic migrations (0001–0005) | Implemented |
| Authentication (email+password, JWT, bcrypt) | Implemented |
| Organizations / Memberships | Implemented |
| RBAC (owner/admin/member) | Implemented |
| Chatbot CRUD + config + lifecycle | Implemented |
| AI Gateway foundation | Implemented |
| Fake providers (`fake-a`, `fake-b`) | Implemented |
| Conversations / Messages | Implemented |
| Real AI providers (OpenAI/Anthropic/Kimi/DeepSeek/…) | Not implemented |
| RAG / embeddings / vector search / knowledge bases | Not implemented |
| Streaming / WebSockets / SSE | Not implemented |
| Widget / public chat runtime | Not implemented |
| Billing / analytics | Not implemented |
| API key management / BYOK | Not implemented |
| Redis usage | Not implemented (dependency present) |

---

## Section 37 — Current Limitations

The system currently **cannot**:

- make real LLM calls (only deterministic fake providers)
- generate assistant responses at runtime (AI Gateway not connected to conversation/message flow)
- stream responses, use WebSockets/SSE
- perform RAG, embeddings, vector search, knowledge-base/document upload
- serve public chat widgets or a public runtime endpoint
- manage provider API keys / BYOK / organization credentials
- bill or analyze usage

These are future foundations, not bugs. The contracts (AIRequest/AIResponse, registries, capabilities, immutable messages) are designed to support them later.

---

## Section 38 — How to Run

Prerequisites: Python venv exists at `AI chatbot`; Docker Desktop running.

```bash
# 1. PostgreSQL (project container with pgvector)
docker compose -f infrastructure/docker-compose.yml up -d postgres

# 2. Environment (from apps/api; copy template once)
copy .env.example .env

# 3. Migrations (from apps/api)
cd "C:\Users\ok\Desktop\Portable AI Chatbot\apps\api"
"C:\Users\ok\Desktop\Portable AI Chatbot\AI chatbot\Scripts\python.exe" -m alembic upgrade head

# 4. Backend
"C:\Users\ok\Desktop\Portable AI Chatbot\AI chatbot\Scripts\python.exe" -m uvicorn app.main:app --reload

# 5. Tests (from apps/api)
"C:\Users\ok\Desktop\Portable AI Chatbot\AI chatbot\Scripts\python.exe" -m pytest
```

---

## Section 39 — Developer Workflow

```text
Read src/PROJECT_RULES.md
 ↓
Read src/backend/architecture.md
 ↓
Inspect code
 ↓
Architecture decision first if needed (update src/)
 ↓
Implement
 ↓
Migration if needed (new Alembic revision; never edit old ones)
 ↓
Tests
 ↓
Migration verification (alembic upgrade head / current / downgrade -1 / upgrade head)
 ↓
Documentation
```

`src/` is the architectural source of truth; new features are defined there before code.
