// Tests for the real ResetPasswordPage: reads ?token= from the URL,
// submits the new password, and handles success/error/missing-token states.
// No AuthProvider needed — the page only calls api.confirmPasswordReset().

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import ResetPasswordPage from "./ResetPasswordPage";
import { jsonResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

function route(response?: Response) {
  fetchMock.mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/api/v1/auth/password-reset/confirm")) {
      return response ?? jsonResponse(204, null);
    }
    return jsonResponse(404, { detail: "Not found" });
  });
}

function renderPage(search = "?token=abc123") {
  return render(
    <MemoryRouter initialEntries={[`/reset-password${search}`]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
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

describe("ResetPasswordPage", () => {
  it("renders the form when a token is present in the URL", () => {
    route();
    renderPage();

    expect(screen.getByRole("heading", { name: "Reset password" })).toBeInTheDocument();
    expect(screen.getByLabelText("New password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset password" })).toBeInTheDocument();
  });

  it("shows a missing-token error and no form when the URL has no token", () => {
    route();
    renderPage("");

    expect(screen.getByText(/Missing reset token/)).toBeInTheDocument();
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });

  it("submits the token and new password, then shows a success message with a sign-in link", async () => {
    route();
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("New password"), "brand-new-password-456");
    await user.click(screen.getByRole("button", { name: "Reset password" }));

    await screen.findByText(/Password updated/);
    const [, init] = fetchMock.mock.calls.find((c) =>
      String(c[0]).endsWith("/password-reset/confirm"),
    )!;
    expect(String(init?.body)).toContain('"token":"abc123"');
    expect(String(init?.body)).toContain('"new_password":"brand-new-password-456"');
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });

  it("shows an error and keeps the form when the token is invalid or expired", async () => {
    route(jsonResponse(400, { detail: "Invalid or expired token" }));
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("New password"), "brand-new-password-456");
    await user.click(screen.getByRole("button", { name: "Reset password" }));

    await screen.findByText("Invalid or expired token");
    expect(screen.getByLabelText("New password")).toBeInTheDocument();
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

    await user.type(screen.getByLabelText("New password"), "brand-new-password-456");
    await user.click(screen.getByRole("button", { name: "Reset password" }));

    expect(screen.getByRole("button", { name: "Resetting…" })).toBeDisabled();

    resolveRequest(jsonResponse(204, null));
    await screen.findByText(/Password updated/);
  });
});
