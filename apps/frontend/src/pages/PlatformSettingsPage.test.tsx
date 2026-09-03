// Tests for the real PlatformSettingsPage: the Stripe key field follows
// BYOK's exact masked/write-only pattern (OrganizationSettingsPage.tsx's
// AI Provider Keys section). fetch is mocked at the global boundary.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PlatformSettingsPage from "./PlatformSettingsPage";
import { jsonResponse } from "../test/helpers";
import type { StripeCredentialStatus } from "../api/types";

const fetchMock = vi.fn<typeof fetch>();

const EXISTING_STATUS: StripeCredentialStatus = {
  masked_key: "••••••••WXYZ",
  updated_at: "2026-01-01T00:00:00Z",
  updated_by_email: "admin@example.com",
};

function renderPage() {
  return render(<PlatformSettingsPage />);
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PlatformSettingsPage", () => {
  it("shows a loading state until settled", async () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => undefined));
    renderPage();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows 'no key configured' when none is set", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, null));
    renderPage();
    await screen.findByText("No Stripe key configured yet.");
  });

  it("shows the masked key and metadata when one is set", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, EXISTING_STATUS));
    renderPage();
    await screen.findByText("••••••••WXYZ", { exact: false });
    expect(screen.getByText("admin@example.com", { exact: false })).toBeInTheDocument();
  });

  it("submits a new key and never displays the raw value", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/platform/settings/stripe") && method === "PUT") {
        return jsonResponse(200, {
          masked_key: "••••••••7890",
          updated_at: "2026-02-01T00:00:00Z",
          updated_by_email: "admin@example.com",
        });
      }
      if (path.endsWith("/platform/settings/stripe")) return jsonResponse(200, null);
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText("No Stripe key configured yet.");
    const input = screen.getByLabelText("Stripe secret key");
    await user.type(input, "sk_test_1234567890");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await screen.findByText("••••••••7890", { exact: false });
    const putCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/platform/settings/stripe") && c[1]?.method === "PUT",
    );
    expect(putCall).toBeDefined();
    expect(JSON.parse(String(putCall?.[1]?.body))).toEqual({ secret_key: "sk_test_1234567890" });
    // The raw key is never rendered back onto the page after saving.
    expect(screen.queryByText("sk_test_1234567890")).not.toBeInTheDocument();
    expect((input as HTMLInputElement).value).toBe("");
  });
});
