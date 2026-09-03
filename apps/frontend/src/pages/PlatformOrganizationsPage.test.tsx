// Tests for the real PlatformOrganizationsPage: list rendering with the
// approved fields. fetch is mocked at the global boundary; no AuthProvider
// needed since the page itself makes no auth decisions (RequirePlatformAdmin
// owns that upstream).

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import PlatformOrganizationsPage from "./PlatformOrganizationsPage";
import { jsonResponse } from "../test/helpers";
import type { PlatformOrganizationList } from "../api/types";

const fetchMock = vi.fn<typeof fetch>();

const LIST: PlatformOrganizationList = {
  items: [
    {
      id: 1,
      name: "Acme Corp",
      slug: "acme-corp",
      created_at: "2026-01-01T00:00:00Z",
      owner_email: "owner@acme.com",
      member_count: 3,
      chatbot_count: 2,
      last_activity_at: "2026-02-01T00:00:00Z",
      disabled_at: null,
      disabled_message: null,
    },
    {
      id: 2,
      name: "Suspended Org",
      slug: "suspended-org",
      created_at: "2026-01-05T00:00:00Z",
      owner_email: "owner@suspended.com",
      member_count: 1,
      chatbot_count: 0,
      last_activity_at: null,
      disabled_at: "2026-02-10T00:00:00Z",
      disabled_message: "Payment overdue.",
    },
  ],
  total: 2,
  limit: 50,
  offset: 0,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <PlatformOrganizationsPage />
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

describe("PlatformOrganizationsPage", () => {
  it("shows a loading state until organizations settle", async () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => undefined));

    renderPage();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders each organization's approved fields, including disabled status", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, LIST));

    renderPage();

    await screen.findByText("Acme Corp");
    expect(screen.getByText("owner@acme.com")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();

    expect(screen.getByText("Suspended Org")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(screen.getByText("never")).toBeInTheDocument();
  });

  it("shows an empty state when there are no organizations", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { items: [], total: 0, limit: 50, offset: 0 }),
    );

    renderPage();

    await screen.findByText("No organizations on the platform yet.");
  });

  it("shows an error when the list request fails", async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, { detail: "boom" }));

    renderPage();

    await screen.findByText("boom");
  });
});
