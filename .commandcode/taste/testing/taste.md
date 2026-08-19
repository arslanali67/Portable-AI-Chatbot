# Taste — Testing

- Test data must be unique per run (uuid-suffixed emails/slugs) so re-runs never collide with leftover rows. Confidence: 0.8
- Uses pytest markers to separate fast unit tests from DB-backed tests (`integration`, `identity`), with `asyncio_default_test_loop_scope = session` in pytest.ini. Confidence: 0.8
- Uses a NullPool test engine with a `get_db` dependency override in conftest.py to avoid asyncpg pooled-connection failures across event loops (TestClient vs pytest-asyncio). Confidence: 0.8
- Writes tests for tenant isolation, role permissions, validation (422s), lifecycle transitions, and cross-tenant denial — not just happy paths. Confidence: 0.8
- External service calls (real provider HTTP, etc.) are mocked in tests — the default suite stays offline and deterministic, and optional live smoke tests run only when real credentials are configured. Confidence: 0.7
- Tests assert security invariants, not just happy paths: responses/errors contain no secrets or internals (no `sk-`, api_key, base_url, tracebacks, provider payloads), SSRF vectors (localhost, loopback/private/metadata IPs, bad schemes/ports/credentials) are rejected, and prompt-injection attempts cannot control provider/model/system_prompt/top_k. Confidence: 0.7
