# PortableAI — Step 18.1 Audit Report

Source-of-truth & complete repository audit. Date: 2026-08-19.

---

## 1. EXECUTIVE SUMMARY

PortableAI was audited end-to-end against its architectural source of truth
(`src/PROJECT_RULES.md` and `src/backend/architecture.md`). The implementation
faithfully realizes the documented design: multi-tenant FastAPI backend with
JWT auth, an AI gateway abstraction (fake + real OpenAI-compatible adapters),
SSRF-safe RAG/file/URL ingestion with pgvector storage, SSE streaming, a
public embeddable widget, a thin React admin dashboard, and production
deployment via Docker.

**Result: COMPLIANT.** No CRITICAL, HIGH, or MEDIUM findings. All findings are
LOW severity: 7 documentation-drift items, 2 minor robustness notes, 1
cleanliness item, and several informational notes. No source-of-truth rule is
violated by the implementation. The only required follow-up is updating the
`src/` docs to reflect implemented state (they are authoritative and have
drifted), then cascading to downstream docs.

## 2. SCOPE & CONSTRAINTS

- **In scope:** full source review of every file under `src/`, `apps/api`,
  `apps/frontend`, `packages/widget`, `infrastructure`, `docs/`, root config
  files, and the two source-of-truth docs.
- **Out of scope (Step 18.1 rules):** no modifications to any code, tests,
  migrations, config, or docs; no dependency installs; no DB/schema changes;
  no destructive or external attacks. SSRF assessment was source-review only.
- **Secrets handling:** any secret found is reported as location + type +
  severity, redacted, never printed verbatim.

## 3. METHODOLOGY

1. Read `src/PROJECT_RULES.md` and `src/backend/architecture.md` in full.
2. Enumerated the complete repository tree (excluding venv, node_modules,
   postgres volume, build artifacts).
3. Read every application source file (models, migrations, repositories,
   services, routes, core, AI layer, RAG layer, schemas, frontend, widget).
4. Cross-checked each source-of-truth requirement against the code.
5. Ran targeted greps for unscoped queries, hardcoded secrets, and XSS sinks.
6. Delegated parallel sub-audits of the test suite and the frontend.
7. Checked repo cleanliness (stray/scratch files, logs).

## 4. REPOSITORY TOPOLOGY

```
root/
├── src/                              architectural source of truth
│   ├── PROJECT_RULES.md              non-negotiable rules (drifted, see §5)
│   └── backend/architecture.md       detailed design (drifted, see §5)
├── apps/api/                         FastAPI backend
│   ├── app/
│   │   ├── main.py                   app entry + middleware wiring
│   │   ├── core/                     config, database, security, deps, logging, rate_limit
│   │   ├── api/v1/                   versioned routers
│   │   ├── models/                   SQLAlchemy 2.x ORM
│   │   ├── schemas/                  Pydantic DTOs
│   │   ├── repositories/             data access (org-scoped)
│   │   ├── services/                 business logic
│   │   ├── ai/                       AI gateway, registries, providers
│   │   └── rag/                      embeddings, ingestion, retrieval, SSRF-safe fetch
│   ├── alembic/                      migrations 0001–0008
│   ├── tests/                        17 test files + conftest
│   ├── requirements.txt, alembic.ini, pytest.ini, Dockerfile
├── apps/frontend/                    React + TS + Vite admin dashboard (nginx image)
├── packages/widget/widget.js         embeddable chat widget (no build)
├── infrastructure/                   docker-compose.prod.yml, .env.example
├── docs/PROJECT_DOCUMENTATION.md     Steps 1–6 only (severely behind; not authoritative)
├── README.md, PROJECT_RULES.md       root pointer docs (drifted pointers)
└── "incomplete prompt file.txt"      stray leftover artifact (see §15 SEC1)
```

Not a git repository at root (no root `.gitignore`); `.gitignore` files exist
under `apps/api` and `apps/frontend`. PostgreSQL runs in Docker
(`portableai-postgres`, pgvector enabled).

## 5. SOURCE-OF-TRUTH COMPLIANCE

### 5.1 Verified compliant (no action)

- **Multi-tenancy at the data layer** (rules §5): every tenant table carries
  `organization_id`; repositories scope queries by org; tenant context derived
  from JWT claims via dependencies. Confirmed in all repository classes.
- **Schema changes only via migrations** (rules §3): app code never creates or
  alters tables; `alembic upgrade head` runs in the API Dockerfile.
- **Credentials not hardcoded** (rules §3, §6): `DATABASE_URL`/`JWT_SECRET`
  come from env/`.env`; no secrets found in source or `alembic.ini`.
- **pgvector enabled + vector abstraction** (rules §3): extension in migration
  0005; embedding/retrieval go through `rag/embeddings.py` +
  `rag/registry.py`; business logic never touches vector SQL.
- **Backend layout** (rules §4): matches documented tree (plus now-implemented
  `ai/` and `rag/`, which the rules §7 predicted).
- **Chatbot entity provider-agnostic** (rules §7): chatbot carries only
  provider/model identifiers resolved against registries at runtime.
- **In-scope §8 deliverables**: all implemented (auth, chatbot CRUD, AI
  gateway, conversations/messages, chat runtime, real OpenAI-compatible
  provider, provider/model discovery, RAG foundation + runtime integration,
  real embeddings + file ingestion, URL ingestion, SSE streaming, public
  widget, production hardening, frontend dashboard, deployment).
- **Out-of-scope list respected** (rules §8, architecture §28): no OAuth,
  no refresh tokens, no MFA, no Redis-backed limiter, no reranking/hybrid
  search, no background workers, no WebSocket — all correctly absent.
- **Production hardening** (architecture §29): fail-fast config in production,
  CORS + trusted hosts from env, safe error handlers, body-size limit (413),
  readiness vs liveness, structured logging with redaction, rate-limiter
  abstraction, JWT hardening, per-route authorization audit documented and
  reflected in code.
- **Frontend** (architecture §30) and **Deployment** (architecture §31):
  implemented as documented (nginx single entry point, SSE `proxy_buffering
  off`, non-root API container, healthchecks, gitignored `.env`).

### 5.2 Documentation drift findings

> Per Step 18.1 rules, `src/` docs are authoritative and must be corrected
> FIRST; downstream docs then updated to match. All findings are LOW severity
> (drift only — the code is correct).

| ID | Severity | Location | Problem |
|----|----------|----------|---------|
| R1 | LOW | `src/PROJECT_RULES.md` §6 line 73 | Says auth uses "short-lived access JWTs and refresh tokens." Refresh tokens are explicitly out of scope (rules §8 line 110, architecture §28/§29) and are NOT implemented. Contradictory. |
| R2 | LOW | `src/PROJECT_RULES.md` §7 lines 77–84 | Header: "AI capabilities are intentionally **not implemented in the MVP**" — stale. §8 (lines 94–107) and the code show the AI gateway, RAG, real OpenAI-compatible provider, embeddings, streaming, and widget are implemented. §7 needs rewriting to "Future extensions on top of the implemented foundation" (as architecture §27 already says). |
| R3 | LOW | `src/PROJECT_RULES.md` §3 line 43 | "vector operations go through a **future** abstraction" — the abstraction now exists (`rag/embeddings.py`, `rag/registry.py`); the rule's intent is satisfied, only the wording is stale. |
| R4 | LOW | `src/backend/architecture.md` §29 line 1006 | "`TRUSTED_HOSTS` (comma-separated) from env" — the implementation and `.env.example` use a JSON-list string (`["example.com"]`). Doc must describe JSON list. |
| R5 | LOW | root `PROJECT_RULES.md` line 13 | "AI/RAG/agents are out of scope for the MVP" — stale pointer; contradicts implemented state. Should defer to `src/backend/architecture.md` §32. |
| R6 | LOW | root `README.md` status | Understates the AI layer: "AI gateway (fake + OpenAI-compatible **mocked** providers)" and "real embeddings (**mocked**)" — the adapters make real network calls (mocked only in tests). Wording should say "real OpenAI-compatible HTTP adapters." |
| R7 | LOW | `docs/PROJECT_DOCUMENTATION.md` | Explicitly a Steps 1–6 doc ("no real provider calls"), 11 steps behind current state. Self-described as limited scope, so informational; should be retired or rewritten if kept. |

## 6. CONFIGURATION & ENVIRONMENT

- `core/config.py`: env-driven, fail-fast in `production` (rejects the
  documented dev-default `JWT_SECRET`, requires all secrets/URLs); dev keeps
  safe defaults. `TRUSTED_HOSTS` parsed as JSON list; CORS origins from env.
- `infrastructure/.env.example` and `apps/api/.env.example`: safe placeholders.
- `apps/api/.env` exists locally: dev `JWT_SECRET` (37 chars — the documented
  dev default) and dev `DATABASE_URL` with local credentials. **Informational,
  LOW** — it is gitignored, never committed, and would be rejected by the
  production fail-fast check. No action required.
- **C2 (LOW):** `redis` is declared in `requirements.txt` but unused (the
  rate limiter is the documented in-memory MVP backend; Redis is a stated
  seam). Informational — intentional per architecture §29.

## 7. MODELS & DATABASE SCHEMA

- Tables: `users`, `organizations`, `memberships`, `chatbots`, `conversations`,
  `messages`, `knowledge_documents`, `document_chunks`, `widget_configs`,
  `widget_sessions`.
- Every tenant table carries `organization_id` (or is derived through a
  parent, e.g. messages via conversation). `widget_sessions` is the documented
  exception — it belongs to the anonymous public boundary, keyed by hashed
  `session_token` and bound to a `widget_config` via `public_key`.
- Enums use native PG enums (chatbot lifecycle: draft/active/archived;
  message role: user/assistant).
- Chatbot carries `provider_id`/`model_id` identifiers only — provider-agnostic
  per rules §7.
- **D1 (LOW):** `widget_configs.enabled` is `NOT NULL` with no
  `server_default`; the service sets it explicitly on create, so no bug today,
  but a `server_default` (e.g. `true`) in a migration would harden inserts.
- Vector columns (`knowledge_documents.embedding`,
  `document_chunks.embedding`) use `Vector` from the pgvector SQLAlchemy type
  with `dim=384` — sourced from `settings.embedding_dimensions` (default 384),
  which the OpenAI-compatible embedding adapter is configured to match.
- `document_chunks` has a cosine-similarity index (`hnsw`), per architecture.

## 8. MIGRATIONS

- 8 versioned migrations (0001–0008), alembic head = 0008. Each reviewed
  against the models: consistent.
  - 0001 schema baseline; 0002–0003 chatbot/model plumbing; 0004
    conversations/messages; 0005 pgvector extension + embedding columns;
    0006 knowledge documents/chunks + widget tables; 0007 ingestion metadata
    (`original_filename`, `file_size`, `content_hash`) + chunk index; 0008
    widget session/index refinement.
- No `app code` creates/alters tables; no credentials in `alembic.ini`
  (`DATABASE_URL` from env). `alembic upgrade head` runs before uvicorn in the
  API container. Compliant.

## 9. REPOSITORY LAYER

- One repository per aggregate; all org-scoped lookups use
  `get_by_id_for_organization` (or membership-scoped variants). Cross-org
  access returns nothing/404. Tenancy enforced at the data layer as required.
- User lookups keyed by email (for login) and id (for JWT sub).
- **RE1 (LOW):** `ChatbotRepository.get(chatbot_id)` is unscoped. It is used
  only by `services/public_widget.py` (lines 56, 76), where the chatbot is
  derived from a validated `public_key`/`session` — the correct public
  boundary, so no risk today. Note for future callers: prefer the scoped
  variant.

## 10. SERVICES LAYER

- Auth, organization, chatbot lifecycle (draft→active→archived with permission
  gates), conversation/message persistence (immutable messages), chat runtime
  (one turn = save user msg → AI gateway → save assistant msg), retrieval,
  context builder (system prompt authoritative, RAG context capped at 8000
  chars), knowledge ingestion (txt/md/pdf/docx, dedup via content hash), URL
  ingestion, widget config/session management, AI management discovery.
- **S1 (LOW, robustness):** in the widget streaming path,
  `services/public_widget.py` loads the `Conversation` by
  `session.conversation_id` without re-checking that
  `conversation.chatbot_id == session.chatbot_id`. The session is created
  server-side bound to a widget config and the token is opaque, so there is no
  reachable misuse; a defensive assertion would be cheap insurance.

## 11. API LAYER / ROUTES

- Routers: `auth`, `organizations`, `chatbots`, `conversations`,
  `chat-runtime`, `knowledge`, `ai-management`, `public-widget`, plus
  `health`/`ready`.
- Middleware ordering in `main.py` is correct (last-added = outermost;
  error-handling outermost). Request logging, body-size cap (default 1 MB →
  413), CORS, trusted hosts, rate limiting all wired.
- Centralized exception handlers return safe `{"detail": ...}` DTOs; SSE
  normalizes provider failures to `error` events. `health` (liveness, no DB)
  and `ready` (`SELECT 1`, 503 on failure) are separate; both excluded from
  request logs.

## 12. AUTHENTICATION & AUTHORIZATION

- JWT access tokens (`sub`, `exp`, `type`); decode requires `type == "access"`
  (`core/security.py`). Generic 401 on all failures — no user enumeration.
- `get_current_user` reloads the user and checks `is_active` on every request.
- Passwords bcrypt-hashed; min length 8 enforced in schema.
- Authorization: membership required for org-scoped routes; admin+ for
  chatbot mutations; owner/admin for archive-of-others and conversation
  reads; public widget is a separate boundary that never trusts
  client-supplied org/chatbot/provider/model/system prompt. All consistent
  with architecture §29 authorization audit.

## 13. AI GATEWAY & PROVIDERS

- `AIGateway` (chat + stream) over a provider registry; model registry,
  capabilities, metadata, contracts, exception hierarchy, streaming
  `AIStreamEvent` normalization (user/start/token/end/error).
- Providers: `fake` (default for offline/test) and `openai_compatible` (real
  HTTP adapter, credentials from env). One persisted assistant message per
  turn regardless of transport.
- Discovery APIs return safe DTOs — no credentials or base URLs exposed.
  Compliant with rules §8 and architecture §27/§29.

## 14. RAG / KNOWLEDGE / INGESTION

- Pipeline: normalize → chunk → embeddings → pgvector → tenant-scoped
  retrieval, shared across file and URL ingestion.
- Embeddings: `openai_embeddings` (real, dimension from
  `settings.embedding_dimensions`, default 384) + `fake` default, via a
  registry.
- SSRF review (source-only, per Step 18.1 rules): `url_validator` resolves and
  validates DNS/IPs (blocks private/loopback/link-local ranges), `http_fetcher`
  re-validates every redirect and caps response size (5 MB); extracted text
  capped (100k chars); robots.txt respected; public pages only. No reachable
  SSRF vector found.
- Retrieval is org+chatbot scoped; context builder keeps the system prompt
  authoritative and truncates RAG context to 8000 chars.

## 15. SECURITY REVIEW

- **XSS:** frontend has zero sinks (`dangerouslySetInnerHTML`/`innerHTML`/
  `eval`/`document.write`); assistant output rendered as React text. The
  embeddable widget uses `textContent` exclusively (with an explicit comment).
  No DOM XSS found.
- **SSRF:** source-review clean (see §14).
- **Secrets:** grep for key material (`sk-…`, private keys, inline passwords/
  secrets) across `apps/api/app` returned nothing. `.env` files are gitignored.
  Only secrets location is the local dev `.env` (informational).
- **SEC1 (LOW, cleanliness):** stray root file `"incomplete prompt file.txt"`
  — a leftover transcript from a previous session. Delete it.
- **SEC2 (INFO):** widget preview in `WidgetConfigPage.tsx` builds an iframe
  via `srcDoc` with a fixed HTML shell + the widget's `public_key`
  (non-secret). Isolated same-origin iframe that loads the real `widget.js`;
  no user-controlled data is interpolated. Safe.
- **SEC3 (INFO):** access token in `localStorage` — standard SPA pattern,
  explicitly documented as a trade-off (no refresh tokens) in architecture §30.

## 16. FRONTEND / ADMIN DASHBOARD

- React + TypeScript + Vite, minimal deps, thin API consumer (no duplicated
  backend logic). Typed client (`api/client.ts`) injects the Bearer token,
  normalizes errors into `ApiError`; DTO types mirror Pydantic schemas.
- Provider/model lists come from the live AI-management API, never hardcoded.
- Chat console consumes the existing SSE endpoint via fetch + ReadableStream.
- Auth flow, protected/guest routes, session-expiry redirect on 401 all match
  architecture §30.

## 17. PUBLIC WIDGET & EMBED

- `packages/widget/widget.js` (231 lines, dependency-free): duplicate-init
  guard, `public_key` from `data-chatbot`, `apiBase` from `data-api`, session
  bootstrapping, SSE parsing, `textContent`-only rendering, token persisted in
  `localStorage` per public key.
- Server side: origin control against `allowed_origins`, per-session
  (30/hr) and per-IP limiters, session binding, no client-trusted config.
  Compliant with architecture §29/§30.

## 18. TESTING & QUALITY

- 17 test files + `conftest.py` (18 files). `conftest` uses a `NullPool` async
  engine on the configured DB with `get_db` overridden — a documented Windows
  event-loop-safe pattern. **286 tests verified passing** (Step 17).
- Coverage by file: `test_ai_gateway` (318 L), `test_ai_management` (235),
  `test_chatbots` (404), `test_chat_runtime` (680), `test_context_builder`
  (132), `test_conversations` (447), `test_database` (42), `test_file_ingestion`
  (246), `test_hardening` (241), `test_health` (17), `test_identity` (251),
  `test_knowledge` (332), `test_openai_embeddings` (120), `test_openai_provider`
  (346), `test_public_widget` (369), `test_streaming` (326), `test_url_ingestion`
  (412).
- Every subsystem (identity, tenancy, chatbot lifecycle, chat runtime incl.
  streaming, gateway/providers, context building, RAG + file + URL ingestion,
  embeddings, public widget, hardening, health) has dedicated coverage.
- **T1 (INFO):** no frontend unit tests — acceptable for a thin client; the
  widget is exercised via the live-preview iframe and `test_public_widget`.

## 19. FINAL VERDICT

**COMPLIANT — audit passed.**

- No CRITICAL, HIGH, or MEDIUM findings.
- The implementation satisfies every non-negotiable rule in
  `src/PROJECT_RULES.md` and matches `src/backend/architecture.md` including
  the §29 hardening and §30/§31 frontend/deployment specifications.
- All 7 findings are LOW-severity **documentation drift** (R1–R7), 2 are
  minor robustness notes (D1, S1 / RE1), 1 is a cleanliness item (SEC1), and
  the rest are informational.

Resolution status (Step 19 — all resolved):

1. **R1/R2/R3** — `src/PROJECT_RULES.md` updated (§6 access-JWT wording, §7 rewritten as "AI capabilities are implemented", §3 pgvector abstraction wording).
2. **R4** — `src/backend/architecture.md` §29 now documents `TRUSTED_HOSTS` as a JSON array.
3. **R5** — root `PROJECT_RULES.md` line 13 rewritten (MVP complete; post-MVP items deferred).
4. **R6** — `README.md` status now says "real OpenAI-compatible HTTP adapters, mocked in tests"; AI-layer sections corrected throughout.
5. **R7** — `docs/PROJECT_DOCUMENTATION.md` marked HISTORICAL (Steps 1–6) and points to current architecture.
6. **D1** — documented decision (no `server_default` added; service-level assignment is the sole insertion path, noted at the model).
7. **S1/RE1** — fixed: widget stream route now re-checks `conversation.chatbot_id == session.chatbot_id` (error event otherwise) with a regression test; `ChatbotRepository.get` renamed `get_public` with a safety docstring. `-m identity` +6 tests (292 total passing).
8. **SEC1** — `incomplete prompt file.txt` deleted in Step 19 cleanup.
9. Embedding-dimension claims corrected to 384 (actual default from `settings.embedding_dimensions`).

See `docs/MVP_RELEASE_REPORT.md` for the full Step 19 verification and release verdict.