// Tests for the real api/client.ts contract: header injection, JSON handling,
// error normalization and 401 token clearing. fetch is mocked at the global
// boundary — no real backend calls.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, getToken, setToken } from "./client";
import type { ApiError } from "./types";
import { jsonResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

function lastInit(): RequestInit {
  const call = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  return (call?.[1] ?? {}) as RequestInit;
}

function lastHeaders(): Record<string, string> {
  return (lastInit().headers ?? {}) as Record<string, string>;
}

beforeEach(() => {
  localStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("sends Authorization: Bearer when a token is stored", async () => {
    setToken("tok123");
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 7 }));

    await api.me();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(lastHeaders()["Authorization"]).toBe("Bearer tok123");
  });

  it("omits the Authorization header when no token exists", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 7 }));

    await api.me();

    expect(lastHeaders()["Authorization"]).toBeUndefined();
  });

  it("sets Content-Type application/json for JSON bodies", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(201, { id: 1, name: "Org", slug: "org", created_at: "x" }),
    );

    await api.createOrganization({ name: "Org", slug: "org" });

    expect(lastHeaders()["Content-Type"]).toBe("application/json");
    expect(String(lastInit().body)).toContain('"slug":"org"');
  });

  it("returns the parsed JSON body on success", async () => {
    const user = {
      id: 7,
      email: "u@example.com",
      full_name: "U",
      is_active: true,
      is_platform_admin: false,
      created_at: "2026-01-01T00:00:00Z",
    };
    fetchMock.mockResolvedValue(jsonResponse(200, user));

    const result = await api.me();

    expect(result).toEqual(user);
  });

  it("resolves to undefined for 204 responses", async () => {
    fetchMock.mockResolvedValue(jsonResponse(204, null));

    await expect(api.revokeWidgetConfig(1, 2)).resolves.toBeUndefined();
    expect(lastInit().method).toBe("DELETE");
  });

  it("normalizes string details into ApiError", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { detail: "Chatbot not found" }));

    await expect(api.getChatbot(1, 2)).rejects.toMatchObject({
      status: 404,
      detail: "Chatbot not found",
      message: "Chatbot not found",
    });
  });

  it("normalizes FastAPI validation arrays into ApiError", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(422, {
        detail: [{ msg: "Field required" }, { msg: "Input should be a valid integer" }],
      }),
    );

    const err = (await api.getChatbot(1, 2).catch((e) => e)) as ApiError;

    expect(err.status).toBe(422);
    expect(err.message).toContain("Field required");
    expect(err.message).toContain("Input should be a valid integer");
  });

  it("clears the stored token on 401 responses", async () => {
    setToken("stale-token");
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: "expired" }));

    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(getToken()).toBeNull();
  });

  it("keeps the stored token on non-401 errors", async () => {
    setToken("valid-token");
    fetchMock.mockResolvedValue(jsonResponse(403, { detail: "Not a member" }));

    await expect(api.getChatbot(1, 2)).rejects.toMatchObject({ status: 403 });
    expect(getToken()).toBe("valid-token");
  });

  it("requests the relative API path when no base URL is configured", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 7 }));

    await api.me();

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/me");
  });

  it("sends credentials:include so the httpOnly refresh cookie can flow", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 7 }));

    await api.me();

    expect(lastInit().credentials).toBe("include");
  });

  it("retries the original request once after a silent refresh succeeds on 401", async () => {
    setToken("expired-token");
    const user = {
      id: 7,
      email: "u@example.com",
      full_name: "U",
      is_active: true,
      is_platform_admin: false,
      created_at: "2026-01-01T00:00:00Z",
    };
    let meCalls = 0;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/auth/refresh")) {
        return jsonResponse(200, { access_token: "new-token", token_type: "bearer" });
      }
      if (path.endsWith("/auth/me")) {
        meCalls += 1;
        return meCalls === 1 ? jsonResponse(401, { detail: "expired" }) : jsonResponse(200, user);
      }
      return jsonResponse(404, { detail: "Not found" });
    });

    const result = await api.me();

    expect(result).toEqual(user);
    expect(getToken()).toBe("new-token");
    // /auth/me (401) -> /auth/refresh (200) -> /auth/me retried (200)
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not loop when the retried request also gets a 401", async () => {
    setToken("expired-token");
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/auth/refresh")) {
        return jsonResponse(200, { access_token: "new-token", token_type: "bearer" });
      }
      return jsonResponse(401, { detail: "still invalid" });
    });

    await expect(api.me()).rejects.toMatchObject({ status: 401 });

    // /auth/me (401) -> /auth/refresh (200) -> /auth/me retried (401) -> stop.
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(getToken()).toBeNull();
  });

  it("propagates the original 401 without retrying when refresh itself fails", async () => {
    setToken("expired-token");
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/auth/refresh")) {
        return jsonResponse(401, { detail: "no refresh token" });
      }
      return jsonResponse(401, { detail: "expired" });
    });

    await expect(api.me()).rejects.toMatchObject({ status: 401 });

    // /auth/me (401) -> /auth/refresh (401) -> stop, no further retry.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getToken()).toBeNull();
  });
});