// Tests for the real LoginPage: form rendering, validation attributes,
// successful login (token storage + hydration + redirect), failure display,
// and submission busy state. All API access is mocked at the global fetch
// boundary; AuthProvider is real (LoginPage consumes useAuth()).

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import LoginPage from "./LoginPage";
import { AuthProvider } from "../auth/AuthContext";
import { getToken } from "../api/client";
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

interface RouteOverrides {
  login?: Response;
  me?: Response;
}

function route(overrides: RouteOverrides = {}) {
  fetchMock.mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/api/v1/auth/login")) {
      return overrides.login ?? jsonResponse(200, { access_token: "jwt-token", token_type: "bearer" });
    }
    if (path.endsWith("/api/v1/auth/me")) {
      return overrides.me ?? jsonResponse(200, USER);
    }
    return jsonResponse(404, { detail: "Not found" });
  });
}

function calls(path: string): Array<[string, RequestInit | undefined]> {
  return fetchMock.mock.calls.filter((call) => String(call[0]).endsWith(path)) as Array<
    [string, RequestInit | undefined]
  >;
}

function renderPage() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<div>Home</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

async function fillCredentials() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email"), "user@example.com");
  await user.type(screen.getByLabelText("Password"), "password123");
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

describe("LoginPage", () => {
  it("renders the login form", () => {
    route();
    renderPage();

    expect(screen.getByRole("heading", { name: "PortableAI" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create one" })).toHaveAttribute("href", "/register");
  });

  it("requires email and password before submission", () => {
    route();
    renderPage();

    const email = screen.getByLabelText("Email");
    const password = screen.getByLabelText("Password");
    expect(email).toBeRequired();
    expect(email).toHaveAttribute("type", "email");
    expect(password).toBeRequired();
    expect(password).toHaveAttribute("type", "password");
  });

  it("logs in, hydrates the user, and redirects to / on success", async () => {
    route();
    const user = userEvent.setup();
    renderPage();

    await fillCredentials();
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByText("Home");
    expect(getToken()).toBe("jwt-token");
    expect(calls("/api/v1/auth/me")).toHaveLength(1);
  });

  it("shows an error and stays on the page when login fails", async () => {
    route({ login: jsonResponse(401, { detail: "Incorrect email or password" }) });
    const user = userEvent.setup();
    renderPage();

    await fillCredentials();
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByText("Incorrect email or password");
    expect(screen.queryByText("Home")).not.toBeInTheDocument();
    expect(getToken()).toBeNull();
  });

  it("disables the submit button and shows busy text while the request is in flight", async () => {
    let resolveLogin!: (response: Response) => void;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/v1/auth/login")) {
        return new Promise<Response>((resolve) => {
          resolveLogin = resolve;
        });
      }
      if (path.endsWith("/api/v1/auth/me")) {
        return jsonResponse(200, USER);
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();
    renderPage();

    await fillCredentials();
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByRole("button", { name: "Signing in…" })).toBeDisabled();

    resolveLogin(jsonResponse(200, { access_token: "jwt-token", token_type: "bearer" }));
    await screen.findByText("Home");
  });

  it("only sends one login request even when submitted twice before the disabled state renders", async () => {
    let loginCalls = 0;
    let resolveLogin!: (response: Response) => void;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/v1/auth/login")) {
        loginCalls += 1;
        return new Promise<Response>((resolve) => {
          resolveLogin = resolve;
        });
      }
      if (path.endsWith("/api/v1/auth/me")) {
        return jsonResponse(200, USER);
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    renderPage();
    await fillCredentials();

    const button = screen.getByRole("button", { name: "Sign in" });
    // Synchronous double click, deliberately not awaiting a re-render between
    // clicks, mirroring the ChatbotsPage regression test for the same class
    // of race between async submission and the disabled-attribute render.
    fireEvent.click(button);
    fireEvent.click(button);

    expect(loginCalls).toBe(1);

    resolveLogin(jsonResponse(200, { access_token: "jwt-token", token_type: "bearer" }));
    await screen.findByText("Home");
  });
});
