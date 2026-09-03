// Tests for the real PlatformOrganizationDetailPage: detail rendering
// (members, chatbots, message count) and the disable/enable control
// submitting with the message field. fetch is mocked at the global
// boundary.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import PlatformOrganizationDetailPage from "./PlatformOrganizationDetailPage";
import { jsonResponse } from "../test/helpers";
import type { PlatformOrganizationDetail } from "../api/types";

const fetchMock = vi.fn<typeof fetch>();

const ACTIVE_ORG: PlatformOrganizationDetail = {
  id: 5,
  name: "Acme Corp",
  slug: "acme-corp",
  created_at: "2026-01-01T00:00:00Z",
  owner_email: "owner@acme.com",
  member_count: 1,
  chatbot_count: 1,
  last_activity_at: "2026-02-01T00:00:00Z",
  disabled_at: null,
  disabled_message: null,
  members: [{ email: "owner@acme.com", role: "owner", joined_at: "2026-01-01T00:00:00Z" }],
  chatbots: [{ name: "Support Bot", slug: "support-bot", status: "active", created_at: "2026-01-02T00:00:00Z" }],
  message_count: 42,
};

const DISABLED_ORG: PlatformOrganizationDetail = {
  ...ACTIVE_ORG,
  disabled_at: "2026-02-10T00:00:00Z",
  disabled_message: "Payment overdue.",
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/platform-admin/organizations/5"]}>
      <Routes>
        <Route
          path="/platform-admin/organizations/:organizationId"
          element={<PlatformOrganizationDetailPage />}
        />
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

describe("PlatformOrganizationDetailPage", () => {
  it("renders members, chatbots, and message count", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, ACTIVE_ORG));

    renderPage();

    await screen.findByText("Acme Corp");
    expect(screen.getByText("owner@acme.com")).toBeInTheDocument();
    expect(screen.getByText("owner")).toBeInTheDocument();
    expect(screen.getByText(/Support Bot/)).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("submits a disable action with the message field", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/platform/organizations/5/disable") && method === "POST") {
        return jsonResponse(200, { ...ACTIVE_ORG, disabled_at: "2026-03-01T00:00:00Z", disabled_message: "Trial expired." });
      }
      if (path.endsWith("/platform/organizations/5")) return jsonResponse(200, ACTIVE_ORG);
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText("Acme Corp");
    const textarea = screen.getByPlaceholderText("This assistant is currently unavailable.");
    await user.type(textarea, "Trial expired.");
    await user.click(screen.getByRole("button", { name: "Disable organization" }));

    await screen.findByText("Enable organization");
    const disableCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/platform/organizations/5/disable") && c[1]?.method === "POST",
    );
    expect(disableCall).toBeDefined();
    expect(JSON.parse(String(disableCall?.[1]?.body))).toEqual({ message: "Trial expired." });
  });

  it("shows the disabled state and submits an enable action", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/platform/organizations/5/enable") && method === "POST") {
        return jsonResponse(200, { ...ACTIVE_ORG, disabled_at: null, disabled_message: null });
      }
      if (path.endsWith("/platform/organizations/5")) return jsonResponse(200, DISABLED_ORG);
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText(/Payment overdue\./);
    await user.click(screen.getByRole("button", { name: "Enable organization" }));

    await screen.findByRole("button", { name: "Disable organization" });
    const enableCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/platform/organizations/5/enable") && c[1]?.method === "POST",
    );
    expect(enableCall).toBeDefined();
  });

  it("submits a manual subscription override", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/platform/organizations/5/subscription") && method === "PATCH") {
        return jsonResponse(200, { tier: "enterprise", status: "active", current_period_end: null });
      }
      if (path.endsWith("/platform/organizations/5")) return jsonResponse(200, ACTIVE_ORG);
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText("Acme Corp");
    await user.type(screen.getByLabelText("Tier"), "enterprise");
    await user.type(screen.getByLabelText("Status"), "active");
    await user.click(screen.getByRole("button", { name: "Set subscription" }));

    await screen.findByText(/tier=enterprise, status=active/);
    const overrideCall = fetchMock.mock.calls.find(
      (c) =>
        String(c[0]).endsWith("/platform/organizations/5/subscription") &&
        c[1]?.method === "PATCH",
    );
    expect(overrideCall).toBeDefined();
    expect(JSON.parse(String(overrideCall?.[1]?.body))).toEqual({
      tier: "enterprise",
      status: "active",
    });
  });
});
