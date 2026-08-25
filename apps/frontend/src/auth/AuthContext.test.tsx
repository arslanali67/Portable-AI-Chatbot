// Tests for the real AuthContext behavior: hydration via /auth/me, login,
// logout and invalid-token cleanup. fetch is mocked at the global boundary.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getToken, setToken } from "../api/client";
import { AuthProvider, useAuth } from "../auth/AuthContext";

const fetchMock = vi.fn<typeof fetch>();

const USER = {
  id: 7,
  email: "user@example.com",
  full_name: "Test User",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function deferredResponse(): { response: Promise<Response>; resolve: (r: Response) => void } {
  let resolve!: (r: Response) => void;
  const promise = new Promise<Response>((res) => {
    resolve = res;
  });
  return { response: promise, resolve };
}

function TestConsumer() {
  const { user, loading, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="state">{JSON.stringify({ user, loading })}</span>
      <button
        type="button"
        onClick={() => void login("user@example.com", "password123").catch(() => undefined)}
      >
        login
      </button>
      <button type="button" onClick={logout}>
        logout
      </button>
    </div>
  );
}

function state(): { user: unknown; loading: boolean } {
  return JSON.parse(screen.getByTestId("state").textContent ?? "{}");
}

function callsTo(path: string): Array<[string | URL, RequestInit | undefined]> {
  return fetchMock.mock.calls.filter((call) => String(call[0]).endsWith(path)) as Array<
    [string | URL, RequestInit | undefined]
  >;
}

beforeEach(() => {
  localStorage.clear();
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/api/v1/auth/login")) {
      return jsonResponse(200, { access_token: "jwt-token", token_type: "bearer" });
    }
    if (path.endsWith("/api/v1/auth/register")) {
      return jsonResponse(201, USER);
    }
    if (path.endsWith("/api/v1/auth/me")) {
      return jsonResponse(200, USER);
    }
    return jsonResponse(404, { detail: "Not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AuthContext", () => {
  it("resolves to signed-out state without calling the API when no token exists", async () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(state().loading).toBe(false));

    expect(state().user).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows loading, then hydrates the user from /auth/me when a token exists", async () => {
    setToken("stored-token");
    const deferred = deferredResponse();
    fetchMock.mockImplementation(() => deferred.response);

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    expect(state().loading).toBe(true);

    deferred.resolve(jsonResponse(200, USER));

    await waitFor(() => expect(state().loading).toBe(false));
    expect(state().user).toMatchObject({ email: "user@example.com" });

    const meCall = callsTo("/api/v1/auth/me")[0];
    const headers = ((meCall?.[1] ?? {}).headers ?? {}) as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer stored-token");
  });

  it("clears an invalid token when /auth/me fails", async () => {
    setToken("expired-token");
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: "expired" }));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(state().loading).toBe(false));

    expect(state().user).toBeNull();
    expect(getToken()).toBeNull();
  });

  it("login stores the access token and hydrates the user", async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await waitFor(() => expect(state().loading).toBe(false));

    await user.click(screen.getByRole("button", { name: "login" }));

    await waitFor(() => expect(getToken()).toBe("jwt-token"));
    await waitFor(() => expect(state().user).toMatchObject({ email: "user@example.com" }));

    const loginCall = callsTo("/api/v1/auth/login")[0];
    const loginHeaders = ((loginCall?.[1] ?? {}).headers ?? {}) as Record<string, string>;
    expect(loginHeaders["Content-Type"]).toBe("application/x-www-form-urlencoded");
    const body = String(loginCall?.[1]?.body ?? "");
    expect(body).toContain("username=user%40example.com");
    expect(body).toContain("password=password123");

    const meCall = callsTo("/api/v1/auth/me")[0];
    const meHeaders = ((meCall?.[1] ?? {}).headers ?? {}) as Record<string, string>;
    expect(meHeaders["Authorization"]).toBe("Bearer jwt-token");
  });

  it("logout clears the token and the user", async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await waitFor(() => expect(state().loading).toBe(false));
    await user.click(screen.getByRole("button", { name: "login" }));
    await waitFor(() => expect(state().user).not.toBeNull());

    await user.click(screen.getByRole("button", { name: "logout" }));

    expect(getToken()).toBeNull();
    expect(state().user).toBeNull();
  });
});