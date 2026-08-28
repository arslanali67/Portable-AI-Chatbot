// Tests for the real AppLayout: sidebar navigation, active-link state,
// Outlet child rendering, and the authenticated user chip/sign-out action.
// AppLayout lives in src/layout/ (not src/components/), matching the actual
// repository structure rather than the reconnaissance report's assumption.
// AuthProvider is real; fetch is mocked at the global boundary.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AppLayout from "./AppLayout";
import { AuthProvider } from "../auth/AuthContext";
import { setToken } from "../api/client";
import { jsonResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

const USER = {
  id: 7,
  email: "user@example.com",
  full_name: "Test User",
  is_active: true,
  is_platform_admin: false,
  created_at: "2026-01-01T00:00:00Z",
};

function renderLayout(initialEntry = "/") {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<div>Dashboard content</div>} />
            <Route path="/organizations" element={<div>Organizations content</div>} />
          </Route>
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

describe("AppLayout", () => {
  it("renders the sidebar navigation and the routed child content", () => {
    renderLayout();

    expect(screen.getByText("PortableAI")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Organizations" })).toHaveAttribute(
      "href",
      "/organizations",
    );
    expect(screen.getByRole("link", { name: "AI Providers" })).toHaveAttribute(
      "href",
      "/providers",
    );
    expect(screen.getByText("Dashboard content")).toBeInTheDocument();
  });

  it("marks the current route's nav link as active", () => {
    renderLayout("/organizations");

    expect(screen.getByText("Organizations content")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Organizations" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("shows the authenticated user's name once hydrated", async () => {
    setToken("stored-token");
    fetchMock.mockResolvedValue(jsonResponse(200, USER));

    renderLayout();

    await screen.findByText("Test User");
  });

  it("does not show a user chip when signed out", () => {
    renderLayout();

    expect(screen.queryByText("Test User")).not.toBeInTheDocument();
  });

  it("signs the user out and clears the user chip", async () => {
    setToken("stored-token");
    fetchMock.mockResolvedValue(jsonResponse(200, USER));
    const user = userEvent.setup();

    renderLayout();
    await screen.findByText("Test User");

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(screen.queryByText("Test User")).not.toBeInTheDocument();
  });
});
