// Tests for the real RequirePlatformAdmin guard: platform-admin
// pass-through, a signed-in-but-non-admin user redirected to /, and a
// signed-out visitor redirected to /login. AuthProvider is real; fetch is
// mocked at the global boundary.

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { RequirePlatformAdmin } from "./RequirePlatformAdmin";
import { AuthProvider } from "../auth/AuthContext";
import { setToken } from "../api/client";
import { jsonResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

const PLAIN_USER = {
  id: 7,
  email: "user@example.com",
  full_name: "Plain User",
  is_active: true,
  is_platform_admin: false,
  created_at: "2026-01-01T00:00:00Z",
};

const ADMIN_USER = {
  ...PLAIN_USER,
  id: 9,
  email: "admin@example.com",
  full_name: "Admin User",
  is_platform_admin: true,
};

function renderGuarded() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/platform-admin"]}>
        <Routes>
          <Route
            path="/platform-admin"
            element={
              <RequirePlatformAdmin>
                <div>Platform content</div>
              </RequirePlatformAdmin>
            }
          />
          <Route path="/login" element={<div>Login page</div>} />
          <Route path="/" element={<div>Home page</div>} />
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

describe("RequirePlatformAdmin", () => {
  it("redirects a signed-out visitor to /login without rendering children", async () => {
    renderGuarded();

    await screen.findByText("Login page");
    expect(screen.queryByText("Platform content")).not.toBeInTheDocument();
  });

  it("redirects a signed-in non-admin user to / without rendering children", async () => {
    setToken("stored-token");
    fetchMock.mockResolvedValue(jsonResponse(200, PLAIN_USER));

    renderGuarded();

    await screen.findByText("Home page");
    expect(screen.queryByText("Platform content")).not.toBeInTheDocument();
  });

  it("renders children for a platform admin", async () => {
    setToken("stored-token");
    fetchMock.mockResolvedValue(jsonResponse(200, ADMIN_USER));

    renderGuarded();

    await screen.findByText("Platform content");
  });
});
