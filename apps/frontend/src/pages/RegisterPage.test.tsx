// Tests for the real RegisterPage: form rendering, validation attributes,
// successful registration (register -> login -> redirect), failure display,
// and submission busy state. All API access is mocked at the global fetch
// boundary; AuthProvider is real (RegisterPage consumes useAuth()).

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import RegisterPage from "./RegisterPage";
import { AuthProvider } from "../auth/AuthContext";
import { getToken } from "../api/client";
import { jsonResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

const USER = {
  id: 9,
  email: "new@example.com",
  full_name: "New User",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

interface RouteOverrides {
  register?: Response;
  login?: Response;
  me?: Response;
}

function route(overrides: RouteOverrides = {}) {
  fetchMock.mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/api/v1/auth/register")) {
      return overrides.register ?? jsonResponse(201, USER);
    }
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
      <MemoryRouter initialEntries={["/register"]}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/" element={<div>Home</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

async function fillForm() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Full name"), "New User");
  await user.type(screen.getByLabelText("Email"), "new@example.com");
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

describe("RegisterPage", () => {
  it("renders the registration form", () => {
    route();
    renderPage();

    expect(screen.getByRole("heading", { name: "Create account" })).toBeInTheDocument();
    expect(screen.getByLabelText("Full name")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });

  it("requires all fields and enforces the minimum password length", () => {
    route();
    renderPage();

    expect(screen.getByLabelText("Full name")).toBeRequired();
    const email = screen.getByLabelText("Email");
    expect(email).toBeRequired();
    expect(email).toHaveAttribute("type", "email");
    const password = screen.getByLabelText("Password");
    expect(password).toBeRequired();
    expect(password).toHaveAttribute("minlength", "8");
  });

  it("registers, logs in, and redirects to / on success", async () => {
    route();
    const user = userEvent.setup();
    renderPage();

    await fillForm();
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await screen.findByText("Home");
    expect(getToken()).toBe("jwt-token");
    expect(calls("/api/v1/auth/register")).toHaveLength(1);
    expect(calls("/api/v1/auth/login")).toHaveLength(1);
  });

  it("shows an error and stays on the page when registration fails", async () => {
    route({ register: jsonResponse(409, { detail: "Email already registered" }) });
    const user = userEvent.setup();
    renderPage();

    await fillForm();
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await screen.findByText("Email already registered");
    expect(screen.queryByText("Home")).not.toBeInTheDocument();
    expect(calls("/api/v1/auth/login")).toHaveLength(0);
  });

  it("shows an error when registration succeeds but the follow-up login fails", async () => {
    route({ login: jsonResponse(401, { detail: "Incorrect email or password" }) });
    const user = userEvent.setup();
    renderPage();

    await fillForm();
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await screen.findByText("Incorrect email or password");
    expect(screen.queryByText("Home")).not.toBeInTheDocument();
  });

  it("disables the submit button and shows busy text while the request is in flight", async () => {
    let resolveRegister!: (response: Response) => void;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/v1/auth/register")) {
        return new Promise<Response>((resolve) => {
          resolveRegister = resolve;
        });
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();
    renderPage();

    await fillForm();
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();

    resolveRegister(jsonResponse(201, USER));
  });

  it("only sends one register request even when submitted twice before the disabled state renders", async () => {
    let registerCalls = 0;
    let resolveRegister!: (response: Response) => void;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/v1/auth/register")) {
        registerCalls += 1;
        return new Promise<Response>((resolve) => {
          resolveRegister = resolve;
        });
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    renderPage();
    await fillForm();

    const button = screen.getByRole("button", { name: "Create account" });
    fireEvent.click(button);
    fireEvent.click(button);

    expect(registerCalls).toBe(1);

    resolveRegister(jsonResponse(201, USER));
  });
});
