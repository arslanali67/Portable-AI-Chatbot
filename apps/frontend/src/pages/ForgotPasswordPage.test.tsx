// Tests for the real ForgotPasswordPage: form rendering, successful
// (enumeration-safe generic) confirmation, and error display. No AuthProvider
// needed — the page only calls api.requestPasswordReset(), not useAuth().

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import ForgotPasswordPage from "./ForgotPasswordPage";
import { jsonResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

function route(response?: Response) {
  fetchMock.mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/api/v1/auth/password-reset/request")) {
      return response ?? jsonResponse(204, null);
    }
    return jsonResponse(404, { detail: "Not found" });
  });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/forgot-password"]}>
      <Routes>
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/login" element={<div>Login page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ForgotPasswordPage", () => {
  it("renders the form", () => {
    route();
    renderPage();

    expect(screen.getByRole("heading", { name: "Forgot password" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send reset link" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to sign in" })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  it("shows a generic confirmation on success, regardless of whether the email exists", async () => {
    route();
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("Email"), "someone@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    await screen.findByText(/If an account exists for that email/);
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
  });

  it("shows an error and keeps the form when the request fails", async () => {
    route(jsonResponse(500, { detail: "Server error" }));
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("Email"), "someone@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    await screen.findByText("Server error");
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });

  it("disables the submit button while the request is in flight", async () => {
    let resolveRequest!: (response: Response) => void;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveRequest = resolve;
        }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("Email"), "someone@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();

    resolveRequest(jsonResponse(204, null));
    await screen.findByText(/If an account exists for that email/);
  });
});
