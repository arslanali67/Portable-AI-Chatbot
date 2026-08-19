# PortableAI — Project Rules

This root-level file is a pointer. The **authoritative** project rules live in `src/PROJECT_RULES.md` — `src/` is the architectural source of truth.

Key rules:

1. `src/` is the architectural source of truth.
2. Define features in `src/` **before** implementing code.
3. No duplicate implementations.
4. Clean architecture; backend is a modular monolith.
5. Multi-tenancy is mandatory.
6. All APIs under `/api/v1/`.
7. MVP is complete: AI gateway, RAG/knowledge, real providers/embeddings, SSE streaming, public widget, and production hardening are implemented. Post-MVP items (agents, WebSockets, OAuth/refresh tokens, billing, advanced retrieval) are listed in `src/PROJECT_RULES.md` and `src/backend/architecture.md`.

See `src/PROJECT_RULES.md` for the full document.
