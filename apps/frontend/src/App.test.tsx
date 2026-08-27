// Tests for the real route table in App.tsx: guest routes, protected routes
// wrapped in RequireAuth (with and without the AppLayout shell), the unknown
// route fallback, and authenticated vs. unauthenticated resolution. App.tsx
// builds its own BrowserRouter, so navigation is driven the standard way for
// that setup: pushState the desired path before rendering, rather than
// rewriting App.tsx to accept an injectable router.

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { setToken } from "./api/client";
import { jsonResponse } from "./test/helpers";

const fetchMock = vi.fn<typeof fetch>();

const USER = {
  id: 7,
  email: "user@example.com",
  full_name: "Test User",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

function routeAuthenticated() {
  fetchMock.mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/api/v1/auth/me")) return jsonResponse(200, USER);
    if (path.endsWith("/api/v1/organizations")) return jsonResponse(200, []);
    if (path.endsWith("/api/v1/ai/providers")) return jsonResponse(200, []);
    return jsonResponse(404, { detail: "Not found" });
  });
}

function goTo(path: string) {
  window.history.pushState({}, "", path);
}

beforeEach(() => {
  localStorage.clear();
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(jsonResponse(404, { detail: "Not found" }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("App routing", () => {
  it("renders the login page as a guest route", () => {
    goTo("/login");

    render(<App />);

    expect(screen.getByRole("heading", { name: "PortableAI" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("renders the register page as a guest route", () => {
    goTo("/register");

    render(<App />);

    expect(screen.getByRole("heading", { name: "Create account" })).toBeInTheDocument();
  });

  it("redirects an unauthenticated visitor from a protected route to /login", async () => {
    goTo("/");

    render(<App />);

    await screen.findByRole("button", { name: "Sign in" });
    expect(window.location.pathname).toBe("/login");
  });

  it("redirects an unknown route to / and then to /login when unauthenticated", async () => {
    goTo("/this-route-does-not-exist");

    render(<App />);

    await screen.findByRole("button", { name: "Sign in" });
    expect(window.location.pathname).toBe("/login");
  });

  it("renders the dashboard inside the app layout for an authenticated visitor", async () => {
    setToken("stored-token");
    routeAuthenticated();
    goTo("/");

    render(<App />);

    await screen.findByRole("heading", { name: "Dashboard" });
    expect(screen.getByRole("link", { name: "AI Providers" })).toBeInTheDocument();
    expect(screen.getByText("Test User")).toBeInTheDocument();
  });

  it("renders the providers page inside the app layout for an authenticated visitor", async () => {
    setToken("stored-token");
    routeAuthenticated();
    goTo("/providers");

    render(<App />);

    await screen.findByRole("heading", { name: "AI Providers" });
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("renders the widget preview route for an authenticated visitor without the app layout shell", async () => {
    setToken("stored-token");
    routeAuthenticated();
    goTo("/organizations/1/chatbots/2/widget-preview?key=pk_1");

    render(<App />);

    await screen.findByText("Preview pane — the launcher appears bottom-right.");
    expect(screen.queryByRole("link", { name: "AI Providers" })).not.toBeInTheDocument();
    expect(screen.queryByText("PortableAI")).not.toBeInTheDocument();
  });
});
