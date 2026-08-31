// Tests for the real WidgetConfigPage: config load/create/revoke flows,
// embed snippet generation and the same-origin preview link. All API access
// is mocked at the global fetch boundary.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import WidgetConfigPage from "./WidgetConfigPage";
import { jsonResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

const EXISTING = {
  public_key: "pk_existing",
  enabled: true,
  revoked_at: null,
  allowed_origins: ["https://example.com"],
  theme_color: null,
  widget_position: null,
  avatar_url: null,
};

const CREATED = {
  public_key: "pk_new",
  enabled: true,
  revoked_at: null,
  allowed_origins: [],
  theme_color: null,
  widget_position: null,
  avatar_url: null,
};

function route(
  options: { get?: Response; post?: Response; patch?: Response; del?: Response; avatar?: Response } = {},
) {
  const { get, post, patch, del, avatar } = options;
  fetchMock.mockImplementation(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.endsWith("/widget-config/avatar")) {
      return avatar ?? jsonResponse(200, { ...EXISTING, avatar_url: "/widget-avatars/new.png" });
    }
    if (path.endsWith("/widget-config")) {
      if (method === "POST") return post ?? jsonResponse(201, CREATED);
      if (method === "PATCH") return patch ?? jsonResponse(200, { ...EXISTING, theme_color: "#112233" });
      if (method === "DELETE") return del ?? jsonResponse(204, null);
      return get ?? jsonResponse(200, EXISTING);
    }
    return jsonResponse(404, { detail: "Not found" });
  });
}

function calls(method: string): Array<[string, RequestInit | undefined]> {
  return fetchMock.mock.calls.filter(
    (call) => ((call[1]?.method ?? "GET").toUpperCase() === method),
  ) as Array<[string, RequestInit | undefined]>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/organizations/4590/chatbots/4746/widget"]}>
      <Routes>
        <Route
          path="/organizations/:organizationId/chatbots/:chatbotId/*"
          element={<WidgetConfigPage />}
        />
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

describe("WidgetConfigPage", () => {
  it("shows a loading state until the configuration request settles", async () => {
    let resolveGet!: (response: Response) => void;
    fetchMock.mockImplementation(
      () => new Promise<Response>((resolve) => { resolveGet = resolve; }),
    );

    renderPage();

    expect(screen.getByText("Loading…")).toBeInTheDocument();

    resolveGet(jsonResponse(200, EXISTING));
    await screen.findByText("pk_existing");
  });

  it("loads an existing credential with key, origins, snippet and preview", async () => {
    route();
    const { container } = renderPage();

    await screen.findByText("pk_existing");

    expect(screen.getByText("Enabled: yes")).toBeInTheDocument();
    // The origins editor only exists in the no-credential create form.
    expect(screen.queryByPlaceholderText("https://example.com")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revoke" })).toBeInTheDocument();

    const pre = container.querySelector("pre");
    expect(pre?.textContent).toContain('src="/widget.js"');
    expect(pre?.textContent).toContain('data-chatbot="pk_existing"');

    const iframe = screen.getByTitle("Widget preview") as HTMLIFrameElement;
    expect(iframe.src).toContain("/widget-preview?key=pk_existing");
  });

  it("shows the create form when no credential exists (404)", async () => {
    route({ get: jsonResponse(404, { detail: "No widget configured" }) });

    renderPage();

    await screen.findByRole("button", { name: "Create widget credential" });
    expect(screen.getByText(/No public widget credential yet/)).toBeInTheDocument();
  });

  it("creates a credential with the entered allowed origins", async () => {
    route({ get: jsonResponse(404, { detail: "No widget configured" }) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByRole("button", { name: "Create widget credential" });

    await user.type(screen.getByRole("textbox"), "https://example.com\nhttps://app.example.com");
    await user.click(screen.getByRole("button", { name: "Create widget credential" }));

    await screen.findByText("pk_new");

    const [, init] = calls("POST")[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      allowed_origins: ["https://example.com", "https://app.example.com"],
    });
  });

  it("revokes the credential after confirmation and returns to the create form", async () => {
    route();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("pk_existing");

    await user.click(screen.getByRole("button", { name: "Revoke" }));

    await screen.findByText(/No public widget credential yet/);
    expect(confirmSpy).toHaveBeenCalledOnce();
    expect(calls("DELETE")).toHaveLength(1);
  });

  it("does not revoke when the confirmation is dismissed", async () => {
    route();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("pk_existing");

    await user.click(screen.getByRole("button", { name: "Revoke" }));

    expect(screen.queryByText(/No public widget credential yet/)).not.toBeInTheDocument();
    expect(screen.getByText("pk_existing")).toBeInTheDocument();
    expect(calls("DELETE")).toHaveLength(0);
  });

  it("shows load errors instead of the page content", async () => {
    route({ get: jsonResponse(500, { detail: "Backend exploded" }) });

    renderPage();

    await screen.findByText("Backend exploded");
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
  });

  it("shows creation errors and stays on the create form", async () => {
    route({
      get: jsonResponse(404, { detail: "No widget configured" }),
      post: jsonResponse(409, { detail: "Duplicate credential" }),
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByRole("button", { name: "Create widget credential" });

    await user.type(screen.getByRole("textbox"), "https://example.com");
    await user.click(screen.getByRole("button", { name: "Create widget credential" }));

    await screen.findByText("Duplicate credential");
    expect(screen.queryByText("pk_new")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create widget credential" })).toBeInTheDocument();
  });

  it("disables the submit button while a creation request is in flight", async () => {
    let resolvePost!: (response: Response) => void;
    fetchMock.mockImplementation(async (_input, init) => {
      if ((init?.method ?? "GET").toUpperCase() === "POST") {
        return new Promise<Response>((resolve) => { resolvePost = resolve; });
      }
      return jsonResponse(404, { detail: "No widget configured" });
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByRole("button", { name: "Create widget credential" });

    await user.click(screen.getByRole("button", { name: "Create widget credential" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled(),
    );

    resolvePost(jsonResponse(201, CREATED));
    await screen.findByText("pk_new");
  });

  it("disables the revoke button while a revoke request is in flight", async () => {
    let resolveDelete!: (response: Response) => void;
    fetchMock.mockImplementation(async (_input, init) => {
      if ((init?.method ?? "GET").toUpperCase() === "DELETE") {
        return new Promise<Response>((resolve) => { resolveDelete = resolve; });
      }
      return jsonResponse(200, EXISTING);
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("pk_existing");

    await user.click(screen.getByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Revoke" })).toBeDisabled());

    resolveDelete(jsonResponse(204, null));
    await screen.findByText(/No public widget credential yet/);
  });

  it("pre-fills the theme form from the loaded config", async () => {
    route({
      get: jsonResponse(200, { ...EXISTING, theme_color: "#2563eb", widget_position: "bottom_left" }),
    });

    renderPage();
    await screen.findByText("pk_existing");

    expect(screen.getByPlaceholderText("#2563eb")).toHaveValue("#2563eb");
    expect(screen.getByRole("combobox")).toHaveValue("bottom_left");
  });

  it("saves theme changes via PATCH", async () => {
    route();
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("pk_existing");

    const colorInput = screen.getByPlaceholderText("#2563eb");
    await user.clear(colorInput);
    await user.type(colorInput, "#112233");
    await user.selectOptions(screen.getByRole("combobox"), "bottom_left");
    await user.click(screen.getByRole("button", { name: "Save theme" }));

    await waitFor(() => expect(calls("PATCH")).toHaveLength(1));
    const [, init] = calls("PATCH")[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      theme_color: "#112233",
      widget_position: "bottom_left",
    });
  });

  it("sends theme_color as null when the field is cleared", async () => {
    route({ get: jsonResponse(200, { ...EXISTING, theme_color: "#2563eb" }) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("pk_existing");

    const colorInput = screen.getByPlaceholderText("#2563eb");
    await user.clear(colorInput);
    await user.click(screen.getByRole("button", { name: "Save theme" }));

    await waitFor(() => expect(calls("PATCH")).toHaveLength(1));
    const [, init] = calls("PATCH")[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      theme_color: null,
      widget_position: null,
    });
  });

  it("uploads an avatar and displays the returned image", async () => {
    route();
    const user = userEvent.setup();

    const { container } = renderPage();
    await screen.findByText("pk_existing");

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["fake"], "avatar.png", { type: "image/png" }));

    await waitFor(() => {
      const avatarPost = fetchMock.mock.calls.find((c) =>
        String(c[0]).endsWith("/widget-config/avatar"),
      );
      expect(avatarPost).toBeDefined();
      expect(avatarPost?.[1]?.body instanceof FormData).toBe(true);
    });

    const img = await screen.findByAltText("Widget avatar");
    expect(img).toHaveAttribute("src", expect.stringContaining("/widget-avatars/new.png"));
  });

  it("shows an error when the theme save fails", async () => {
    route({ patch: jsonResponse(422, { detail: "Invalid theme_color" }) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("pk_existing");

    await user.click(screen.getByRole("button", { name: "Save theme" }));

    await screen.findByText("Invalid theme_color");
  });
});