// Tests for the real OrganizationsPage: list/empty rendering, create flow,
// failure display, navigation, and busy state. All API access is mocked at
// the global fetch boundary.

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import OrganizationsPage from "./OrganizationsPage";
import { jsonResponse } from "../test/helpers";
import type { Organization } from "../api/types";

const fetchMock = vi.fn<typeof fetch>();

const ORG_A: Organization = { id: 1, name: "Acme", slug: "acme", created_at: "2026-01-01T00:00:00Z" };

interface RouteOverrides {
  list?: Response;
  create?: Response;
}

function route(overrides: RouteOverrides = {}) {
  fetchMock.mockImplementation(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.endsWith("/api/v1/organizations")) {
      if (method === "POST") return overrides.create ?? jsonResponse(201, { ...ORG_A, id: 2, name: "New Org", slug: "new-org" });
      return overrides.list ?? jsonResponse(200, []);
    }
    return jsonResponse(404, { detail: "Not found" });
  });
}

function calls(method: string): Array<[string, RequestInit | undefined]> {
  return fetchMock.mock.calls.filter(
    (call) => (call[1]?.method ?? "GET").toUpperCase() === method,
  ) as Array<[string, RequestInit | undefined]>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/organizations"]}>
      <Routes>
        <Route path="/organizations" element={<OrganizationsPage />} />
        <Route path="/organizations/:organizationId" element={<div>Org detail page</div>} />
      </Routes>
    </MemoryRouter>,
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

describe("OrganizationsPage", () => {
  it("shows a loading state until the list request settles", async () => {
    let resolveList!: (response: Response) => void;
    fetchMock.mockImplementation(
      () => new Promise<Response>((resolve) => { resolveList = resolve; }),
    );

    renderPage();

    expect(screen.getByText("Loading…")).toBeInTheDocument();

    resolveList(jsonResponse(200, []));
    await waitForLoadingToFinish();
  });

  async function waitForLoadingToFinish() {
    await screen.findByText("No organizations yet. Create one to begin.");
  }

  it("shows the empty state when there are no organizations", async () => {
    route();
    renderPage();

    await waitForLoadingToFinish();
  });

  it("renders the organization list", async () => {
    route({ list: jsonResponse(200, [ORG_A]) });
    renderPage();

    await screen.findByText("Acme");
    expect(screen.getByText("/acme")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Acme/ })).toHaveAttribute("href", "/organizations/1");
  });

  it("shows a load error instead of the list", async () => {
    route({ list: jsonResponse(500, { detail: "Organizations failed" }) });
    renderPage();

    await screen.findByText("Organizations failed");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("creates an organization and appends it to the list without a full reload", async () => {
    route({ list: jsonResponse(200, [ORG_A]) });
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Acme");

    await user.type(screen.getByPlaceholderText("Organization name"), "New Org");
    await user.type(screen.getByPlaceholderText("slug"), "new-org");

    const getCallsBefore = calls("GET").length;
    await user.click(screen.getByRole("button", { name: "Create" }));

    await screen.findByText("New Org");
    expect(screen.getByText("Acme")).toBeInTheDocument();

    const [, init] = calls("POST")[0];
    expect(JSON.parse(String(init?.body))).toEqual({ name: "New Org", slug: "new-org" });
    // The page appends the created org locally rather than refetching the list.
    expect(calls("GET")).toHaveLength(getCallsBefore);

    expect(screen.getByPlaceholderText("Organization name")).toHaveValue("");
    expect(screen.getByPlaceholderText("slug")).toHaveValue("");
  });

  it("shows an error and keeps the entered values when creation fails", async () => {
    route({ create: jsonResponse(409, { detail: "Slug already taken" }) });
    const user = userEvent.setup();
    renderPage();

    await waitForLoadingToFinish();

    await user.type(screen.getByPlaceholderText("Organization name"), "Dup Org");
    await user.type(screen.getByPlaceholderText("slug"), "dup-org");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await screen.findByText("Slug already taken");
    expect(screen.getByPlaceholderText("Organization name")).toHaveValue("Dup Org");
    expect(screen.getByPlaceholderText("slug")).toHaveValue("dup-org");
  });

  it("navigates to the organization detail page from the Open button", async () => {
    route({ list: jsonResponse(200, [ORG_A]) });
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Acme");
    await user.click(screen.getByRole("button", { name: "Open" }));

    await screen.findByText("Org detail page");
  });

  it("disables the create button and shows busy text while the request is in flight", async () => {
    let resolveCreate!: (response: Response) => void;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/organizations") && method === "GET") return jsonResponse(200, []);
      if (path.endsWith("/organizations") && method === "POST") {
        return new Promise<Response>((resolve) => { resolveCreate = resolve; });
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();
    renderPage();

    await waitForLoadingToFinish();
    await user.type(screen.getByPlaceholderText("Organization name"), "New Org");
    await user.type(screen.getByPlaceholderText("slug"), "new-org");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();

    resolveCreate(jsonResponse(201, { ...ORG_A, id: 2, name: "New Org", slug: "new-org" }));
    await screen.findByText("New Org");
  });

  it("only sends one create request even when submitted twice before the disabled state renders", async () => {
    let createCalls = 0;
    let resolveCreate!: (response: Response) => void;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/organizations") && method === "GET") return jsonResponse(200, []);
      if (path.endsWith("/organizations") && method === "POST") {
        createCalls += 1;
        return new Promise<Response>((resolve) => { resolveCreate = resolve; });
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();
    renderPage();

    await waitForLoadingToFinish();
    await user.type(screen.getByPlaceholderText("Organization name"), "New Org");
    await user.type(screen.getByPlaceholderText("slug"), "new-org");

    const button = screen.getByRole("button", { name: "Create" });
    fireEvent.click(button);
    fireEvent.click(button);

    expect(createCalls).toBe(1);

    resolveCreate(jsonResponse(201, { ...ORG_A, id: 2, name: "New Org", slug: "new-org" }));
    await screen.findByText("New Org");
  });
});
