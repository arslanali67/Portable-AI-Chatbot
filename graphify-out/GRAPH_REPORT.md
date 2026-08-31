# Graph Report - Portable-AI-Chatbot  (2026-08-31)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2067 nodes · 5259 edges · 90 communities (85 shown, 5 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 251 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `047a7eda`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_auth_sessions.py
- test_url_ingestion.py
- KnowledgeService
- test_file_ingestion.py
- conversations.py
- AIManagementService
- test_chat_runtime.py
- AuthContext.tsx
- test_organizations.py
- test_openai_embeddings.py
- test_conversations.py
- client.ts
- test_widget_config.py
- test_chatbots.py
- jsonResponse
- Base
- organizations.py
- test_ai_management.py
- test_public_widget.py
- errorMessage
- test_knowledge.py
- devDependencies
- test_openai_provider.py
- test_identity.py
- AIRequest
- v1/public_widget.py
- OpenAICompatibleHTTPProvider
- MembershipRole
- services/chat_runtime.py
- PublicWidgetService
- ChatbotsPage.test.tsx
- ProviderRegistry
- test_ai_gateway.py
- test_streaming.py
- ContextBuilder
- OrganizationRepository
- dependencies.py
- ._transition
- compilerOptions
- models/chatbot.py
- ChunkRepository
- ProviderMetadata
- MembershipRepository
- test_hardening.py
- MessageRole
- ChatbotRepository
- OrganizationService
- agentrouter
- build_rate_limiter
- WidgetConfigService
- DashboardPage.test.tsx
- WidgetPosition
- KnowledgeDocumentRepository
- WidgetConfigPage.tsx
- ChatbotsPage
- OrganizationSettingsPage.test.tsx
- widget.js
- readiness_check
- schemas/organization.py
- env.py
- test_database.py
- ResetPasswordPage.tsx
- get_db
- .fail_fast_production
- decode_access_token
- ai/__init__.py
- .environment_valid
- rag/__init__.py
- test_widget_config_revoke_persists

## God Nodes (most connected - your core abstractions)
1. `errorMessage()` - 51 edges
2. `MembershipRole` - 46 edges
3. `_setup_owner()` - 41 edges
4. `_setup_owner()` - 40 edges
5. `KnowledgeService` - 39 edges
6. `AIGateway` - 38 edges
7. `_setup_owner()` - 38 edges
8. `AIRequest` - 36 edges
9. `_create_conv()` - 35 edges
10. `_create_bot()` - 34 edges

## Surprising Connections (you probably didn't know these)
- `AuthService` --uses--> `PasswordResetTokenRepository`  [INFERRED]
  apps/api/app/services/auth.py → apps/api/app/repositories/auth_token.py
- `AuthService` --uses--> `RefreshTokenRepository`  [INFERRED]
  apps/api/app/services/auth.py → apps/api/app/repositories/auth_token.py
- `KnowledgeService` --uses--> `HTMLTextExtractor`  [INFERRED]
  apps/api/app/services/knowledge.py → apps/api/app/rag/html_extractor.py
- `KnowledgeService` --uses--> `FetchError`  [INFERRED]
  apps/api/app/services/knowledge.py → apps/api/app/rag/http_fetcher.py
- `KnowledgeService` --uses--> `SecureHTTPFetcher`  [INFERRED]
  apps/api/app/services/knowledge.py → apps/api/app/rag/http_fetcher.py

## Import Cycles
- None detected.

## Communities (90 total, 5 thin omitted)

### Community 0 - "test_auth_sessions.py"
Cohesion: 0.05
Nodes (73): _clear_refresh_cookie(), confirm_password_reset(), login(), logout(), me(), AsyncSession, get, post (+65 more)

### Community 1 - "test_url_ingestion.py"
Cohesion: 0.05
Nodes (71): EmptyHTMLTextError, HTMLTextExtractor, Exception, HTML text extraction — untrusted HTML to clean text. No DB/repo/auth/embed…, BadContentTypeError, _content_type_allowed(), FetchError, _parse_robots() (+63 more)

### Community 2 - "KnowledgeService"
Cohesion: 0.07
Nodes (53): _chatbot_404(), delete_document(), _document_404(), get_document(), ingest_document(), ingest_file(), ingest_url(), list_documents() (+45 more)

### Community 3 - "test_file_ingestion.py"
Cohesion: 0.05
Nodes (57): get_logger(), Any, Structured application logging. Redaction helpers ensure secrets never reach…, Redact sensitive keys within a plain dict, recursively., Configure root logging for the application., Return a module-level logger with app defaults applied., redact_dict(), setup_logging() (+49 more)

### Community 4 - "conversations.py"
Cohesion: 0.08
Nodes (51): archive_conversation(), chat_with_conversation(), _conversation_404(), create_conversation(), create_message(), get_conversation(), list_chatbot_conversations(), list_messages() (+43 more)

### Community 5 - "AIManagementService"
Cohesion: 0.07
Nodes (32): _get_management(), get_model(), get_provider(), list_models(), list_providers(), AsyncSession, get, patch (+24 more)

### Community 6 - "test_chat_runtime.py"
Cohesion: 0.13
Nodes (58): _auth(), _capture_gateway(), _chat(), _create_bot(), _create_conv(), _create_org(), _email(), _ingest_knowledge() (+50 more)

### Community 7 - "AuthContext.tsx"
Cohesion: 0.06
Nodes (33): getToken(), setToken(), User, App(), fetchMock, routeAuthenticated(), USER, AuthContext (+25 more)

### Community 8 - "test_organizations.py"
Cohesion: 0.13
Nodes (53): _add_member(), _add_user_with_role(), _auth(), _bot_payload(), _create_org(), _delete_member(), _delete_org(), _email() (+45 more)

### Community 9 - "test_openai_embeddings.py"
Cohesion: 0.08
Nodes (36): EmbeddingMetadata, EmbeddingProvider, Protocol, Vector, Embedding abstraction — provider-agnostic. RAG/retrieval code never contains…, FakeEmbeddingProvider, Vector, Deterministic offline fake embedding provider. Stable vectors (hash-based),… (+28 more)

### Community 10 - "test_conversations.py"
Cohesion: 0.14
Nodes (50): _auth(), _create_bot(), _create_conv(), _create_org(), _email(), _login(), _post_message(), Conversation + message tests — ownership, lifecycle, roles, tenant isolation,… (+42 more)

### Community 11 - "client.ts"
Cohesion: 0.08
Nodes (41): api, attemptRefresh(), clearToken(), NO_REFRESH_RETRY_SUFFIXES, normalizeError(), rawFetch(), request(), streamChat() (+33 more)

### Community 12 - "test_widget_config.py"
Cohesion: 0.10
Nodes (44): delete_avatar(), ImageTooLargeError, InvalidImageError, Exception, Path, Widget avatar upload — local-disk storage for chatbot widget branding.…, Identify PNG/JPEG/WebP by magic bytes. Returns None for anything else,…, Resolve a served filename to a path inside the upload dir, or None if the… (+36 more)

### Community 13 - "test_chatbots.py"
Cohesion: 0.13
Nodes (48): _auth(), _bot_payload(), _create_bot(), _create_org(), _email(), _login(), Chatbot CRUD tests — tenant isolation, roles, validation, lifecycle. Require…, Status is not freely choosable — extra field rejected or ignored. (+40 more)

### Community 14 - "jsonResponse"
Cohesion: 0.06
Nodes (32): BOT, fetchMock, route(), RouteOverrides, CONV_A, CONV_ARCHIVED, CONV_B, fetchMock (+24 more)

### Community 15 - "Base"
Cohesion: 0.08
Nodes (29): Base, Declarative base for all ORM models., AI model override — platform-admin enable/disable layered on the code registry., AI provider override — platform-admin enable/disable layered on the code…, Adds created_at / updated_at columns to a model., TimestampMixin, Conversation, Conversation ORM model — one chatbot, one organization, one owner. (+21 more)

### Community 16 - "organizations.py"
Cohesion: 0.12
Nodes (35): add_member(), create_organization(), delete_organization(), get_organization(), list_members(), list_organizations(), AsyncSession, delete (+27 more)

### Community 17 - "test_ai_management.py"
Cohesion: 0.14
Nodes (38): _auth(), _create_bot(), _create_org(), _email(), _login(), _promote_platform_admin(), AI management API tests — read-only provider/model discovery + chatbot…, An organization OWNER — the highest existing MembershipRole — must not satisfy… (+30 more)

### Community 18 - "test_public_widget.py"
Cohesion: 0.14
Nodes (37): _auth(), _email(), _login(), _parse_sse(), Public widget tests — config, sessions, origin control, streaming chat, RAG,…, Regression: multiple credentials for one chatbot must not break session…, Regression: a widget session must never stream into a conversation bound to a…, The eager config fetch must never create a widget_sessions row. (+29 more)

### Community 19 - "errorMessage"
Cohesion: 0.11
Nodes (33): RetrievedChunk, errorMessage(), ChatbotDetailPage(), ChatConsolePage(), archive(), beginPending(), createConversation(), endPending() (+25 more)

### Community 20 - "test_knowledge.py"
Cohesion: 0.16
Nodes (37): _auth(), _chunks(), _email(), _ingest(), _login(), Knowledge/RAG tests — ingestion, retrieval, tenant isolation, delete,…, Proves fusion genuinely combines both signals rather than falling back to one.…, More matching chunks exist than top_k; the final count is still exactly top_k… (+29 more)

### Community 21 - "devDependencies"
Cohesion: 0.05
Nodes (37): dependencies, react, react-dom, react-router-dom, devDependencies, jsdom, @testing-library/jest-dom, @testing-library/react (+29 more)

### Community 22 - "test_openai_provider.py"
Cohesion: 0.17
Nodes (33): _gemini_provider(), _generate(), MockTransport, _ok_response(), _provider(), asyncio, Exception, Response (+25 more)

### Community 23 - "test_identity.py"
Cohesion: 0.21
Nodes (33): _auth_header(), _craft_token(), _create_org(), _email(), _login(), asyncio, Identity system API tests. Require the project's Docker PostgreSQL (docker…, _register() (+25 more)

### Community 24 - "AIRequest"
Cohesion: 0.14
Nodes (19): AIRequest, AIResponse, AIUsage, Provider-neutral AI contracts. No FastAPI, SQLAlchemy, or provider SDK imports.…, AIProvider, OpenAICompatibleProvider, Protocol, Provider interface and OpenAI-compatible base. Core contracts are provider-… (+11 more)

### Community 25 - "v1/public_widget.py"
Cohesion: 0.12
Nodes (29): _build_config_response(), _client_ip(), create_session(), get_public_config(), AsyncSession, Chatbot, get, HTTPException (+21 more)

### Community 26 - "OpenAICompatibleHTTPProvider"
Cohesion: 0.13
Nodes (21): AICapability, AIAuthenticationError, AICapabilityNotSupportedError, AIError, AIInvalidRequestError, AIModelNotFoundError, AIProviderError, AIRateLimitError (+13 more)

### Community 27 - "MembershipRole"
Cohesion: 0.18
Nodes (30): activate_chatbot(), archive_chatbot(), create_chatbot(), create_widget_config(), delete_chatbot(), get_chatbot(), _get_chatbot_or_404(), get_widget_config() (+22 more)

### Community 28 - "services/chat_runtime.py"
Cohesion: 0.13
Nodes (21): ChatRequest, ChatResponse, ChatRuntimeMessage, BaseModel, field_validator, Chat runtime schemas. Client sends only content. Server owns…, Safe message DTO for the runtime response (never raw DB/provider)., AccessDeniedError (+13 more)

### Community 29 - "PublicWidgetService"
Cohesion: 0.12
Nodes (13): WidgetSession, generate_session_token(), AsyncSession, WidgetConfig, Widget repositories — public_key config + anonymous sessions., WidgetConfigRepository, WidgetSessionRepository, PublicWidgetService (+5 more)

### Community 30 - "ChatbotsPage.test.tsx"
Cohesion: 0.08
Nodes (21): ModelInfo, Provider, LANGUAGE_OPTIONS, BOT_ACTIVE, BOT_DRAFT, fetchMock, MODEL_A_SMALL, MODEL_B_SMALL (+13 more)

### Community 31 - "ProviderRegistry"
Cohesion: 0.09
Nodes (13): AIProviderUnavailableError, Provider endpoint unreachable or down., AI Gateway — provider- and model-agnostic orchestration. Validates, resolves…, DuplicateModelError, ModelRegistry, Exception, Model registry — (provider_id, model_id) → ModelMetadata. No DB enums; ids are…, DuplicateProviderError (+5 more)

### Community 32 - "test_ai_gateway.py"
Cohesion: 0.29
Nodes (25): AIGateway, _model(), _provider(), pytest_run(), AI gateway tests — registries, gateway, capabilities, errors, multi-provider,…, _registry_pair(), _request(), test_fake_provider_deterministic_offline() (+17 more)

### Community 33 - "test_streaming.py"
Cohesion: 0.23
Nodes (25): _auth(), _email(), _login(), _messages(), _parse_sse(), Streaming chat (SSE) tests — fake provider deterministic stream, RAG,…, Ingest knowledge, stream a matching question; fake provider echoes the…, _register() (+17 more)

### Community 34 - "ContextBuilder"
Cohesion: 0.23
Nodes (18): AIMessage, AIMessageRole, Enum, str, RetrievedChunkResponse, ContextBuilder, Context builder — pure assembly of system prompt + RAG context + history. No…, _chunk() (+10 more)

### Community 35 - "OrganizationRepository"
Cohesion: 0.12
Nodes (8): RefreshToken, AsyncSession, RefreshTokenRepository, OrganizationRepository, AsyncSession, Organization, Organization repository — data access for organizations., AsyncSession

### Community 36 - "dependencies.py"
Cohesion: 0.12
Nodes (16): get_current_user(), AsyncSession, Membership, Organization, User, Shared FastAPI dependencies: current user, organization membership., Validate Bearer JWT, load user from database, check active., Verify organization exists and current user belongs to it. Membership is always… (+8 more)

### Community 37 - "._transition"
Cohesion: 0.13
Nodes (12): ChatbotNotFoundError, DuplicateSlugError, InvalidProviderModelError, InvalidStatusTransitionError, AsyncSession, Chatbot, ChatbotCreate, ChatbotUpdate (+4 more)

### Community 38 - "compilerOptions"
Cohesion: 0.09
Nodes (21): compilerOptions, allowImportingTsExtensions, isolatedModules, jsx, lib, module, moduleResolution, noEmit (+13 more)

### Community 39 - "models/chatbot.py"
Cohesion: 0.17
Nodes (15): Chatbot, _enum_values(), Chatbot ORM model — organization-owned, provider-agnostic configuration., Store enum values (lowercase) in the database, not member names., ChatbotStatus, ChatbotVisibility, str, ChatbotCreate (+7 more)

### Community 40 - "ChunkRepository"
Cohesion: 0.11
Nodes (12): get_embedding_provider(), Resolve provider; raise clear error if unavailable/disabled., ChunkRepository, Any, AsyncSession, Document chunk repository — scoped storage + hybrid (vector + full-text) search., Hybrid search: fuse a vector-similarity candidate list and a full-text…, ChatbotNotFoundError (+4 more)

### Community 41 - "ProviderMetadata"
Cohesion: 0.16
Nodes (14): AICapability, str, AuthenticationType, CompatibilityType, ModelMetadata, ProviderMetadata, str, Provider and model metadata. Never store API secrets here. (+6 more)

### Community 42 - "MembershipRepository"
Cohesion: 0.13
Nodes (10): MembershipRole, Dependency factory: require membership with at least the given role. Usage:…, require_organization_role(), MembershipRepository, AsyncSession, Membership, MembershipRole, Membership rows joined with their user's email/full name. Selects plain columns… (+2 more)

### Community 43 - "test_hardening.py"
Cohesion: 0.17
Nodes (10): get_settings(), Application settings, loaded from environment / .env., Settings, Tests for production hardening: - readiness endpoint - body-size limit…, test_development_config_allows_dev_secret(), test_invalid_environment_rejected(), test_production_config_fails_fast_on_weak_secret(), test_production_config_fails_fast_with_debug() (+2 more)

### Community 44 - "MessageRole"
Cohesion: 0.16
Nodes (9): MessageRole, Message, Message ORM model — immutable text history within a conversation., MessageRepository, Any, AsyncSession, Message, Message repository — scoped through conversation ownership. (+1 more)

### Community 45 - "ChatbotRepository"
Cohesion: 0.17
Nodes (6): ChatbotRepository, AsyncSession, Chatbot, Chatbot repository — tenant-scoped data access. Authenticated flows must use…, Unscoped-by-organization lookup for the public widget boundary only. Safe…, AsyncSession

### Community 46 - "OrganizationService"
Cohesion: 0.22
Nodes (9): DuplicateSlugError, OrganizationNotFoundError, OrganizationService, Exception, Organization, OrganizationCreate, OrganizationUpdate, User (+1 more)

### Community 47 - "agentrouter"
Cohesion: 0.13
Nodes (14): models, name, npm, options, name, name, name, claude-opus-4-8 (+6 more)

### Community 48 - "build_rate_limiter"
Cohesion: 0.16
Nodes (10): build_rate_limiter(), InMemoryRateLimiter, Protocol, RateLimiter, Rate limiter abstraction for public endpoints. Routes depend on the…, Protocol: a rate limiter keyed by a string. Returns True if allowed., Sliding-window in-memory rate limiter (process-local)., Factory for limiter backends. Currently returns the in-memory implementation. A… (+2 more)

### Community 49 - "WidgetConfigService"
Cohesion: 0.21
Nodes (8): generate_public_key(), AsyncSession, Exception, WidgetConfig, Validate + store a new avatar, replacing (not accumulating) any previous file.…, WidgetConfigNotFoundError, WidgetConfigService, WidgetPosition

### Community 50 - "DashboardPage.test.tsx"
Cohesion: 0.19
Nodes (8): Chatbot, DashboardPage(), load(), OrgSummary, fetchMock, ORG_A, ORG_B, USER

### Community 51 - "WidgetPosition"
Cohesion: 0.23
Nodes (10): WidgetPosition, _enum_values(), Widget configuration ORM model — public embed credential per chatbot., Store enum values (lowercase) in the database, not member names., WidgetConfig, BaseModel, Widget config admin schemas — create/update/read for the org-scoped…, Partial update. avatar_url is deliberately absent — it is server-set only, via… (+2 more)

### Community 52 - "KnowledgeDocumentRepository"
Cohesion: 0.25
Nodes (4): KnowledgeDocumentRepository, AsyncSession, KnowledgeDocument, Knowledge document repository — tenant/chatbot scoped.

### Community 53 - "WidgetConfigPage.tsx"
Cohesion: 0.27
Nodes (6): API_BASE_URL, WidgetPosition, POSITION_OPTIONS, widgetApiBase(), widgetScriptSrc(), WidgetPreviewPage()

### Community 54 - "ChatbotsPage"
Cohesion: 0.36
Nodes (8): ChatbotsPage(), beginPending(), changeStatus(), endPending(), onSubmit(), openCreate(), remove(), resetForm()

### Community 55 - "OrganizationSettingsPage.test.tsx"
Cohesion: 0.22
Nodes (7): BOB_MEMBERSHIP, fetchMock, ORG, OWNER_MEMBERSHIP, route(), RouteOverrides, VIEWER

### Community 56 - "widget.js"
Cohesion: 0.42
Nodes (7): applyPosition(), applyTheme(), initSession(), renderMessage(), sendMessage(), setBusy(), showError()

### Community 57 - "readiness_check"
Cohesion: 0.29
Nodes (7): health_check(), AsyncSession, get, Response, Liveness: the process is up. Never depends on infrastructure., Readiness: required infrastructure reachable. Performs a lightweight SELECT 1…, readiness_check()

### Community 58 - "schemas/organization.py"
Cohesion: 0.36
Nodes (7): MembershipCreate, OrganizationCreate, OrganizationResponse, OrganizationUpdate, BaseModel, Organization schemas., Partial update — name only. Slug is immutable.

### Community 59 - "env.py"
Cohesion: 0.38
Nodes (5): do_run_migrations(), Alembic migration environment. Database URL comes from application settings…, run_async_migrations(), run_migrations_online(), Connection

### Community 60 - "test_database.py"
Cohesion: 0.43
Nodes (6): asyncio, Database integration tests. Require the project's Docker PostgreSQL: `docker…, test_database_session_created(), test_pgvector_extension_exists(), test_postgresql_reachable(), test_simple_query_works()

### Community 61 - "ResetPasswordPage.tsx"
Cohesion: 0.33
Nodes (4): ResetPasswordPage(), onSubmit(), fetchMock, route()

### Community 62 - "get_db"
Cohesion: 0.33
Nodes (5): get_db(), AsyncSession, Centralized async database foundation. One engine, one session factory.…, FastAPI dependency yielding a request-scoped AsyncSession., test_readiness_not_ready_when_db_down()

### Community 81 - "decode_access_token"
Cohesion: 0.67
Nodes (3): decode_access_token(), Decode and validate a JWT access token. Raises jwt.PyJWTError on failure.…, test_jwt_token_type_claim_enforced()

## Knowledge Gaps
- **118 isolated node(s):** `AICapability`, `ChatbotStatus`, `ChatbotVisibility`, `ConversationStatus`, `MessageRole` (+113 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_db()` connect `get_db` to `test_auth_sessions.py`, `test_url_ingestion.py`, `KnowledgeService`, `conversations.py`, `AIManagementService`, `dependencies.py`, `test_hardening.py`, `organizations.py`, `readiness_check`, `MembershipRole`, `v1/public_widget.py`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Why does `MembershipRole` connect `MembershipRole` to `KnowledgeService`, `conversations.py`, `dependencies.py`, `models/chatbot.py`, `MembershipRepository`, `OrganizationService`, `Base`, `organizations.py`, `test_identity.py`, `schemas/organization.py`, `services/chat_runtime.py`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Why does `ProviderRegistry` connect `ProviderRegistry` to `test_ai_gateway.py`, `AIManagementService`, `test_chat_runtime.py`, `ProviderMetadata`, `test_openai_provider.py`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Are the 31 inferred relationships involving `MembershipRole` (e.g. with `activate_chatbot()` and `archive_chatbot()`) actually correct?**
  _`MembershipRole` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `KnowledgeService` (e.g. with `Chunker` and `TextChunk`) actually correct?**
  _`KnowledgeService` has 14 INFERRED edges - model-reasoned connections that need verification._
- **What connects `AICapability`, `ChatbotStatus`, `ChatbotVisibility` to the rest of the system?**
  _118 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_auth_sessions.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05158324821246169 - nodes in this community are weakly interconnected._