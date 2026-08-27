// Tests for the real RequireAuth guard: authenticated pass-through, the
// hydration loading state, and the redirect-to-/login for a signed-out
// visitor. AuthProvider is real; fetch is mocked at the global boundary.

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { RequireAuth } from "./RequireAuth";
import { AuthProvider } from "../auth/AuthContext";
import { setToken } from "../api/client";
import { jsonResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

const USER = {
  id: 7,
  email: "user@example.com",
  full_name: "Test User",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

function renderGuarded() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/protected"]}>
        <Routes>
          <Route
            path="/protected"
            element={
              <RequireAuth>
                <div>Protected content</div>
              </RequireAuth>
            }
          />
          <Route path="/login" element={<div>Login page</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("RequireAuth", () => {
  it("redirects a signed-out visitor to /login without rendering children", async () => {
    renderGuarded();

    await screen.findByText("Login page");
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("shows a loading state while the token is being hydrated", async () => {
    setToken("stored-token");
    let resolveMe!: (response: Response) => void;
    fetchMock.mockImplementation(
      () => new Promise<Response>((resolve) => { resolveMe = resolve; }),
    );

    renderGuarded();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();

    resolveMe(jsonResponse(200, USER));
    await screen.findByText("Protected content");
  });

  it("renders children once an authenticated user is hydrated", async () => {
    setToken("stored-token");
    fetchMock.mockResolvedValue(jsonResponse(200, USER));

    renderGuarded();

    await screen.findByText("Protected content");
  });

  it("redirects to /login when hydration fails (invalid/expired token)", async () => {
    setToken("expired-token");
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: "expired" }));

    renderGuarded();

    await screen.findByText("Login page");
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });
});
