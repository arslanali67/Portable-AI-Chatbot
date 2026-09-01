// Tests for the real DashboardPage: org/chatbot aggregation, loading/empty
// states, and partial-failure tolerance (one org's chatbot list failing must
// not blank the rest of the dashboard). AuthProvider is real (DashboardPage
// reads the current user via useAuth()); fetch is mocked at the global
// boundary.

import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import DashboardPage from "./DashboardPage";
import { AuthProvider } from "../auth/AuthContext";
import { setToken } from "../api/client";
import { jsonResponse } from "../test/helpers";
import type { Chatbot, Organization } from "../api/types";

const fetchMock = vi.fn<typeof fetch>();

const USER = {
  id: 7,
  email: "user@example.com",
  full_name: "Test User",
  is_active: true,
  is_platform_admin: false,
  created_at: "2026-01-01T00:00:00Z",
};

const ORG_A: Organization = { id: 1, name: "Acme", slug: "acme", created_at: "2026-01-01T00:00:00Z" };
const ORG_B: Organization = { id: 2, name: "Globex", slug: "globex", created_at: "2026-01-01T00:00:00Z" };

function bot(overrides: Partial<Chatbot>): Chatbot {
  return {
    id: 1,
    organization_id: 1,
    name: "Bot",
    slug: "bot",
    description: "",
    system_prompt: "",
    welcome_message: "",
    status: "draft",
    visibility: "private",
    language: "en",
    provider_id: "fake",
    model_id: "fake-model-small",
    rag_enabled: true,
    rag_top_k: null,
    response_schema: null,
    tools: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function statValue(label: string): string {
  const labelEl = screen.getByText(label, { selector: ".stat-label" });
  const card = labelEl.closest(".stat-card") as HTMLElement;
  return within(card).getByText(/.*/, { selector: ".stat-value" }).textContent ?? "";
}

function renderPage() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/organizations" element={<div>Organizations page</div>} />
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

describe("DashboardPage", () => {
  it("shows a loading state until organizations and chatbots settle", async () => {
    fetchMock.mockImplementation(
      () => new Promise<Response>(() => undefined),
    );

    renderPage();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows the empty state when the user belongs to no organizations", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/v1/organizations")) return jsonResponse(200, []);
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText(/No organizations yet\./);
    expect(screen.getByRole("link", { name: "Create one" })).toHaveAttribute(
      "href",
      "/organizations",
    );
    expect(statValue("Organizations")).toBe("0");
    expect(statValue("Chatbots")).toBe("0");
    expect(statValue("Active")).toBe("0");
  });

  it("aggregates organizations and their chatbots into the stat cards and list", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/v1/organizations")) return jsonResponse(200, [ORG_A, ORG_B]);
      if (path.endsWith("/organizations/1/chatbots")) {
        return jsonResponse(200, [bot({ id: 1, status: "active" }), bot({ id: 2, status: "draft" })]);
      }
      if (path.endsWith("/organizations/2/chatbots")) {
        return jsonResponse(200, [bot({ id: 3, organization_id: 2, status: "active" })]);
      }
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText("Acme");
    expect(screen.getByText("Globex")).toBeInTheDocument();
    expect(statValue("Organizations")).toBe("2");
    expect(statValue("Chatbots")).toBe("3");
    expect(statValue("Active")).toBe("2");
    expect(screen.getByText(/2 chatbots/)).toBeInTheDocument();
    expect(screen.getByText(/1 chatbot(?!s)/)).toBeInTheDocument();
  });

  it("still renders every organization when one org's chatbot request fails", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/v1/organizations")) return jsonResponse(200, [ORG_A, ORG_B]);
      if (path.endsWith("/organizations/1/chatbots")) {
        return jsonResponse(500, { detail: "Chatbots unavailable" });
      }
      if (path.endsWith("/organizations/2/chatbots")) {
        return jsonResponse(200, [bot({ id: 3, organization_id: 2 })]);
      }
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    // Dashboard must not go blank: both orgs render, the failed one falls
    // back to zero chatbots instead of aborting the whole page.
    await screen.findByText("Acme");
    expect(screen.getByText("Globex")).toBeInTheDocument();
    expect(screen.getByText(/0 chatbots/)).toBeInTheDocument();
    expect(screen.getByText(/1 chatbot(?!s)/)).toBeInTheDocument();
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
  });

  it("shows an error alongside the (empty) skeleton when the organization list itself fails", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/v1/organizations")) return jsonResponse(500, { detail: "Dashboard failed" });
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText("Dashboard failed");
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText(/No organizations yet\./)).toBeInTheDocument();
  });

  it("welcomes the authenticated user by name once hydrated", async () => {
    setToken("stored-token");
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/v1/auth/me")) return jsonResponse(200, USER);
      if (path.endsWith("/api/v1/organizations")) return jsonResponse(200, []);
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText("Welcome, Test User.");
  });
});
