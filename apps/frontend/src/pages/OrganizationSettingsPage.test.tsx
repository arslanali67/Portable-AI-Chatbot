// Tests for the real OrganizationSettingsPage: detail/rename/delete, member
// list, add/role-change/remove (including the per-row pendingRef duplicate-
// click guard and the self-removal "Leave organization" affordance). Fetch
// is mocked at the global boundary; AuthProvider is real (the page reads the
// current user via useAuth() to identify the viewer's own row).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import OrganizationSettingsPage from "./OrganizationSettingsPage";
import { AuthProvider } from "../auth/AuthContext";
import { setToken } from "../api/client";
import { jsonResponse } from "../test/helpers";
import type { Membership, Organization } from "../api/types";

const fetchMock = vi.fn<typeof fetch>();

const VIEWER = {
  id: 1,
  email: "owner@example.com",
  full_name: "Owner User",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

const ORG: Organization = {
  id: 4590,
  name: "Acme",
  slug: "acme",
  created_at: "2026-01-01T00:00:00Z",
};

const OWNER_MEMBERSHIP: Membership = {
  id: 1,
  organization_id: 4590,
  user_id: 1,
  role: "owner",
  created_at: "2026-01-01T00:00:00Z",
  user_email: "owner@example.com",
  user_full_name: "Owner User",
};

const BOB_MEMBERSHIP: Membership = {
  id: 2,
  organization_id: 4590,
  user_id: 99,
  role: "member",
  created_at: "2026-01-01T00:00:00Z",
  user_email: "bob@example.com",
  user_full_name: "Bob Member",
};

interface RouteOverrides {
  org?: Response;
  members?: Response;
  patchOrg?: Response;
  deleteOrg?: Response;
  addMember?: Response;
  patchMember?: Response;
  deleteMember?: Response;
}

function route(overrides: RouteOverrides = {}) {
  fetchMock.mockImplementation(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();

    if (path.endsWith("/api/v1/auth/me")) {
      return jsonResponse(200, VIEWER);
    }
    if (/\/members\/\d+$/.test(path)) {
      if (method === "PATCH") return overrides.patchMember ?? jsonResponse(200, BOB_MEMBERSHIP);
      if (method === "DELETE") return overrides.deleteMember ?? jsonResponse(204, null);
    }
    if (path.endsWith("/members")) {
      if (method === "POST") {
        return (
          overrides.addMember ??
          jsonResponse(201, {
            id: 3,
            organization_id: 4590,
            user_id: 100,
            role: "member",
            created_at: "2026-01-01T00:00:00Z",
            user_email: "new@example.com",
            user_full_name: "New Member",
          })
        );
      }
      return overrides.members ?? jsonResponse(200, [OWNER_MEMBERSHIP, BOB_MEMBERSHIP]);
    }
    if (/\/organizations\/4590$/.test(path)) {
      if (method === "PATCH") return overrides.patchOrg ?? jsonResponse(200, { ...ORG, name: "Renamed Acme" });
      if (method === "DELETE") return overrides.deleteOrg ?? jsonResponse(204, null);
      return overrides.org ?? jsonResponse(200, ORG);
    }
    return jsonResponse(404, { detail: "Not found" });
  });
}

function calls(method: string, matcher?: RegExp): Array<[string, RequestInit | undefined]> {
  return fetchMock.mock.calls.filter((call) => {
    const path = String(call[0]);
    const usedMethod = ((call[1]?.method ?? "GET") as string).toUpperCase();
    return usedMethod === method && (!matcher || matcher.test(path));
  }) as Array<[string, RequestInit | undefined]>;
}

function renderPage() {
  setToken("stored-token");
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/organizations/4590/settings"]}>
        <Routes>
          <Route
            path="/organizations/:organizationId/settings"
            element={<OrganizationSettingsPage />}
          />
          <Route path="/organizations" element={<div>Organizations list page</div>} />
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

describe("OrganizationSettingsPage", () => {
  it("shows a loading state until the organization and members settle", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/api/v1/auth/me")) return jsonResponse(200, VIEWER);
      return new Promise<Response>(() => undefined);
    });

    renderPage();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("shows a load error instead of the page content", async () => {
    route({ org: jsonResponse(500, { detail: "Organization failed" }) });

    renderPage();

    await screen.findByText("Organization failed");
    expect(screen.queryByRole("heading", { name: "Organization settings" })).not.toBeInTheDocument();
  });

  it("renders the organization detail and every member with role/email/name", async () => {
    route();

    renderPage();

    await screen.findByRole("heading", { name: "Acme" });
    expect(screen.getByText(/\/acme/)).toBeInTheDocument();
    expect(screen.getByText("Owner User")).toBeInTheDocument();
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
    expect(screen.getByText("Bob Member")).toBeInTheDocument();
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
  });

  it("renames the organization", async () => {
    route();
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Acme");

    const nameInput = screen.getByLabelText("Name");
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed Acme");
    await user.click(screen.getByRole("button", { name: "Save name" }));

    await waitFor(() => expect(calls("PATCH", /\/organizations\/4590$/)).toHaveLength(1));
    const [, init] = calls("PATCH", /\/organizations\/4590$/)[0];
    expect(JSON.parse(String(init?.body))).toEqual({ name: "Renamed Acme" });
    await screen.findByDisplayValue("Renamed Acme");
  });

  it("shows an error and keeps the typed name when rename fails", async () => {
    route({ patchOrg: jsonResponse(422, { detail: "Name is required" }) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Acme");

    const nameInput = screen.getByLabelText("Name");
    await user.clear(nameInput);
    await user.type(nameInput, "Bad Name");
    await user.click(screen.getByRole("button", { name: "Save name" }));

    await screen.findByText("Name is required");
    expect(screen.getByLabelText("Name")).toHaveValue("Bad Name");
  });

  it("disables the rename button and shows busy text while saving", async () => {
    let resolvePatch!: (response: Response) => void;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/api/v1/auth/me")) return jsonResponse(200, VIEWER);
      if (/\/organizations\/4590$/.test(path) && method === "PATCH") {
        return new Promise<Response>((resolve) => { resolvePatch = resolve; });
      }
      if (/\/organizations\/4590$/.test(path)) return jsonResponse(200, ORG);
      if (path.endsWith("/members")) return jsonResponse(200, [OWNER_MEMBERSHIP, BOB_MEMBERSHIP]);
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Acme");

    await user.click(screen.getByRole("button", { name: "Save name" }));

    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();

    resolvePatch(jsonResponse(200, { ...ORG, name: "Acme" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Saving…" })).not.toBeInTheDocument(),
    );
  });

  it("does not delete the organization when the confirmation is dismissed", async () => {
    route();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Acme");

    await user.click(screen.getByRole("button", { name: "Delete organization" }));

    expect(calls("DELETE", /\/organizations\/4590$/)).toHaveLength(0);
    expect(screen.getByText("Acme")).toBeInTheDocument();
  });

  it("deletes the organization after confirmation and navigates to the organizations list", async () => {
    route();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Acme");

    await user.click(screen.getByRole("button", { name: "Delete organization" }));

    expect(confirmSpy.mock.calls[0][0]).toContain("chatbots, conversations, and knowledge");
    await screen.findByText("Organizations list page");
    expect(calls("DELETE", /\/organizations\/4590$/)).toHaveLength(1);
  });

  it("shows an error and stays on the page when deletion fails", async () => {
    route({ deleteOrg: jsonResponse(403, { detail: "Only an owner may delete" }) });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Acme");

    await user.click(screen.getByRole("button", { name: "Delete organization" }));

    await screen.findByText("Only an owner may delete");
    expect(screen.queryByText("Organizations list page")).not.toBeInTheDocument();
  });

  it("adds a member with the entered email and role", async () => {
    route();
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Acme");

    await user.type(screen.getByPlaceholderText("Member email"), "new@example.com");
    await user.click(screen.getByRole("button", { name: "Add member" }));

    await screen.findByText("New Member");
    const [, init] = calls("POST", /\/members$/)[0];
    expect(JSON.parse(String(init?.body))).toEqual({ email: "new@example.com", role: "member" });
  });

  it("shows an error when adding a member fails", async () => {
    route({ addMember: jsonResponse(404, { detail: "User not found" }) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Acme");

    await user.type(screen.getByPlaceholderText("Member email"), "ghost@example.com");
    await user.click(screen.getByRole("button", { name: "Add member" }));

    await screen.findByText("User not found");
  });

  it("disables the add-member button while the request is in flight", async () => {
    let resolveAdd!: (response: Response) => void;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/api/v1/auth/me")) return jsonResponse(200, VIEWER);
      if (path.endsWith("/members") && method === "POST") {
        return new Promise<Response>((resolve) => { resolveAdd = resolve; });
      }
      if (path.endsWith("/members")) return jsonResponse(200, [OWNER_MEMBERSHIP, BOB_MEMBERSHIP]);
      if (/\/organizations\/4590$/.test(path)) return jsonResponse(200, ORG);
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Acme");

    await user.type(screen.getByPlaceholderText("Member email"), "new@example.com");
    await user.click(screen.getByRole("button", { name: "Add member" }));

    expect(screen.getByRole("button", { name: "Adding…" })).toBeDisabled();

    resolveAdd(
      jsonResponse(201, {
        id: 3,
        organization_id: 4590,
        user_id: 100,
        role: "member",
        created_at: "2026-01-01T00:00:00Z",
        user_email: "new@example.com",
        user_full_name: "New Member",
      }),
    );
    await screen.findByText("New Member");
  });

  it("changes a member's role", async () => {
    route({ patchMember: jsonResponse(200, { ...BOB_MEMBERSHIP, role: "admin" }) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Bob Member");

    await user.selectOptions(screen.getByLabelText("Role for Bob Member"), "admin");

    await waitFor(() => expect(calls("PATCH", /\/members\/2$/)).toHaveLength(1));
    const [, init] = calls("PATCH", /\/members\/2$/)[0];
    expect(JSON.parse(String(init?.body))).toEqual({ role: "admin" });
    await waitFor(() => expect(screen.getByLabelText("Role for Bob Member")).toHaveValue("admin"));
  });

  it("shows the last-owner 409 error and leaves the role unchanged", async () => {
    route({
      patchMember: jsonResponse(409, { detail: "Organization must keep at least one owner" }),
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Owner User");

    await user.selectOptions(screen.getByLabelText("Role for Owner User"), "admin");

    await screen.findByText("Organization must keep at least one owner");
    expect(screen.getByLabelText("Role for Owner User")).toHaveValue("owner");
  });

  it("asks for confirmation before removing another member", async () => {
    route();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Bob Member");

    await user.click(screen.getByRole("button", { name: "Remove" }));

    expect(confirmSpy).toHaveBeenCalledWith("Remove Bob Member from this organization?");
    await waitFor(() => expect(calls("DELETE", /\/members\/2$/)).toHaveLength(1));
  });

  it("removes a member after confirmation", async () => {
    route();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Bob Member");

    await user.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(screen.queryByText("Bob Member")).not.toBeInTheDocument());
  });

  it("shows an error and keeps the member when removal fails", async () => {
    route({ deleteMember: jsonResponse(403, { detail: "Insufficient role to remove this member" }) });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Bob Member");

    await user.click(screen.getByRole("button", { name: "Remove" }));

    await screen.findByText("Insufficient role to remove this member");
    expect(screen.getByText("Bob Member")).toBeInTheDocument();
  });

  it("only sends one remove request even when clicked twice before the disabled state renders", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let removeCalls = 0;
    let resolveDelete!: (response: Response) => void;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/api/v1/auth/me")) return jsonResponse(200, VIEWER);
      if (/\/organizations\/4590$/.test(path)) return jsonResponse(200, ORG);
      if (path.endsWith("/members")) return jsonResponse(200, [OWNER_MEMBERSHIP, BOB_MEMBERSHIP]);
      if (/\/members\/2$/.test(path) && method === "DELETE") {
        removeCalls += 1;
        return new Promise<Response>((resolve) => { resolveDelete = resolve; });
      }
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();
    await screen.findByText("Bob Member");

    const button = screen.getByRole("button", { name: "Remove" });
    // Synchronous double click, deliberately not awaiting a re-render between
    // clicks, mirroring the ChatbotsPage regression test for the same race
    // between async submission and the disabled-attribute render.
    fireEvent.click(button);
    fireEvent.click(button);

    expect(removeCalls).toBe(1);

    resolveDelete(jsonResponse(204, null));
    await waitFor(() => expect(screen.queryByText("Bob Member")).not.toBeInTheDocument());
  });

  it("lets the viewer leave the organization via a distinct self-removal affordance", async () => {
    route({ deleteMember: jsonResponse(204, null) });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderPage();
    await screen.findByText("Owner User");

    const leaveButton = screen.getByRole("button", { name: "Leave organization" });
    expect(leaveButton).toBeInTheDocument();
    // Distinct from the "Remove" wording used for other members.
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);

    const user = userEvent.setup();
    await user.click(leaveButton);

    expect(confirmSpy).toHaveBeenCalledWith("Leave this organization? You will lose access immediately.");
    await screen.findByText("Organizations list page");
    expect(calls("DELETE", /\/members\/1$/)).toHaveLength(1);
  });
});
