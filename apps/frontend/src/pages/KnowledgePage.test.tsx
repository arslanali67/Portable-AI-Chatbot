// Tests for the real KnowledgePage: ingestion (text/URL/file), search,
// deletion, list rendering and error/disabled states. All API access is
// mocked at the global fetch boundary.

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import KnowledgePage from "./KnowledgePage";
import { jsonResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

const DOC_A = {
  id: 21,
  name: "Intro Doc",
  source_type: "text",
  status: "ready",
  chunk_count: 3,
  original_filename: null,
  source_uri: null,
  created_at: "2026-08-01T10:00:00Z",
};

const DOC_B = {
  id: 22,
  name: "Site Page",
  source_type: "url",
  status: "ready",
  chunk_count: 1,
  original_filename: null,
  source_uri: "https://example.com",
  created_at: "2026-08-02T10:00:00Z",
};

function listResponse(items: unknown[]) {
  return jsonResponse(200, { items, total: items.length });
}

interface RouteOverrides {
  get?: Response;
  postText?: Response;
  postUrl?: Response;
  postFile?: Response;
  del?: Response;
  search?: Response;
}

function route(overrides: RouteOverrides = {}) {
  const { get, postText, postUrl, postFile, del, search } = overrides;
  fetchMock.mockImplementation(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.endsWith("/knowledge/search")) {
      return search ?? jsonResponse(200, { results: [] });
    }
    if (path.endsWith("/knowledge/documents/file")) {
      return postFile ?? jsonResponse(201, DOC_B);
    }
    if (path.endsWith("/knowledge/documents/url")) {
      return postUrl ?? jsonResponse(201, DOC_B);
    }
    if (/\/knowledge\/documents\/\d+$/.test(path)) {
      return del ?? jsonResponse(204, null);
    }
    if (path.endsWith("/knowledge/documents")) {
      if (method === "POST") return postText ?? jsonResponse(201, DOC_A);
      return get ?? listResponse([]);
    }
    return jsonResponse(404, { detail: "Not found" });
  });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/organizations/4590/chatbots/4746/knowledge"]}>
      <Routes>
        <Route
          path="/organizations/:organizationId/chatbots/:chatbotId/*"
          element={<KnowledgePage />}
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

describe("KnowledgePage", () => {
  it("shows a loading state until the document list settles", async () => {
    let resolveGet!: (response: Response) => void;
    fetchMock.mockImplementation(
      () => new Promise<Response>((resolve) => { resolveGet = resolve; }),
    );

    renderPage();

    expect(screen.getByText("Loading…")).toBeInTheDocument();

    resolveGet(listResponse([DOC_A]));
    await screen.findByText("Intro Doc");
  });

  it("renders the document table with type, status and chunk counts", async () => {
    route({ get: listResponse([DOC_A, DOC_B]) });

    renderPage();

    await screen.findByText("Documents (2)");
    expect(screen.getByText("Intro Doc")).toBeInTheDocument();
    const row = screen.getByText("Site Page").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("url")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("ready")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("1")).toBeInTheDocument();
  });

  it("shows the empty state when no documents exist", async () => {
    route();

    renderPage();

    await screen.findByText(/No documents yet\. Add text, a URL, or a file above\./);
    expect(screen.getByText("Documents (0)")).toBeInTheDocument();
  });

  it("shows a load error instead of the table", async () => {
    route({ get: jsonResponse(500, { detail: "List failed" }) });

    renderPage();

    await screen.findByText("List failed");
    expect(screen.queryByText("Documents (")).not.toBeInTheDocument();
  });

  it("ingests text and reloads the list with cleared inputs", async () => {
    route({ get: listResponse([DOC_A]) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Intro Doc");
    const getCallsBefore = fetchMock.mock.calls.length;

    await user.type(screen.getByPlaceholderText("Document name"), "Notes");
    await user.type(screen.getByPlaceholderText("Paste content to index…"), "hello world");
    await user.click(screen.getByRole("button", { name: "Ingest text" }));

    await waitFor(() => expect(screen.getByPlaceholderText("Document name")).toHaveValue(""));

    const postCall = fetchMock.mock.calls
      .filter((c) => String(c[0]).endsWith("/knowledge/documents") && c[1]?.method === "POST")[0];
    expect(postCall).toBeDefined();
    expect(String(postCall?.[1]?.body)).toContain('"name":"Notes"');
    expect(String(postCall?.[1]?.body)).toContain('"content":"hello world"');
    expect(String(postCall?.[1]?.body)).toContain('"source_type":"text"');
    // The list was refreshed after successful ingestion.
    expect(fetchMock.mock.calls.length).toBeGreaterThan(getCallsBefore + 1);
  });

  it("ingests a URL with an optional title", async () => {
    route({ get: listResponse([]) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/No documents yet/);

    const urlPanel = screen.getByText("Ingest URL", { selector: "h3" }).closest(
      "form",
    ) as HTMLElement;
    await user.type(
      within(urlPanel).getByPlaceholderText("https://example.com/article"),
      "https://example.com/guide",
    );
    await user.type(within(urlPanel).getByPlaceholderText("Optional title"), "Guide");
    await user.click(within(urlPanel).getByRole("button", { name: "Ingest URL" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          (c) =>
            String(c[0]).endsWith("/knowledge/documents/url") &&
            String(c[1]?.body).includes('"url":"https://example.com/guide"') &&
            String(c[1]?.body).includes('"title":"Guide"'),
        ),
      ).toBe(true),
    );
  });

  it("uploads a file via multipart FormData once a file is chosen", async () => {
    route({ get: listResponse([]) });
    const user = userEvent.setup();

    const { container } = renderPage();
    await screen.findByText(/No documents yet/);

    const uploadButton = screen.getByRole("button", { name: "Upload" });
    expect(uploadButton).toBeDisabled();

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["hello"], "notes.txt", { type: "text/plain" }));
    expect(uploadButton).toBeEnabled();

    await user.click(uploadButton);

    await waitFor(() => {
      const filePost = fetchMock.mock.calls.find((c) =>
        String(c[0]).endsWith("/knowledge/documents/file"),
      );
      expect(filePost).toBeDefined();
      expect(filePost?.[1]?.body instanceof FormData).toBe(true);
    });
  });

  it("deletes a document after confirmation and refreshes the list", async () => {
    route({ get: listResponse([DOC_B]) });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Site Page");

    const row = screen.getByText("Site Page").closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledOnce());
    expect(
      fetchMock.mock.calls.some(
        (c) => /\/knowledge\/documents\/22$/.test(String(c[0])) && c[1]?.method === "DELETE",
      ),
    ).toBe(true);
    // List reloaded after deletion.
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3));
  });

  it("does not delete when the confirmation is dismissed", async () => {
    route({ get: listResponse([DOC_B]) });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Site Page");

    const row = screen.getByText("Site Page").closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Delete" }));

    expect(fetchMock.mock.calls.some((c) => c[1]?.method === "DELETE")).toBe(false);
  });

  it("searches knowledge and renders scored results", async () => {
    route({
      search: jsonResponse(200, {
        results: [
          { document_id: 21, chunk_id: 5, content: "zebra facts here", score: 0.9123, metadata: null },
        ],
      }),
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/No documents yet/);

    await user.type(screen.getByPlaceholderText("Search knowledge…"), "zebra");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByText("Search results (1)");
    expect(screen.getByText("zebra facts here")).toBeInTheDocument();
    expect(screen.getByText(/doc #21 · score 0\.9123/)).toBeInTheDocument();
  });

  it("shows the no-matches state for empty search results", async () => {
    route();
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/No documents yet/);

    await user.type(screen.getByPlaceholderText("Search knowledge…"), "anything");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByText("Search results (0)");
    expect(screen.getByText("No matches.")).toBeInTheDocument();
  });

  it("ignores blank searches without calling the API", async () => {
    route();
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/No documents yet/);

    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith("/knowledge/search"))).toBe(
      false,
    );
  });

  it("disables ingest buttons while a text ingestion is in flight", async () => {
    let resolvePost!: (response: Response) => void;
    fetchMock.mockImplementation(async (_input, init) => {
      if ((init?.method ?? "GET").toUpperCase() === "POST") {
        return new Promise<Response>((resolve) => { resolvePost = resolve; });
      }
      return listResponse([]);
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText(/No documents yet/);

    await user.type(screen.getByPlaceholderText("Document name"), "N");
    await user.type(screen.getByPlaceholderText("Paste content to index…"), "C");
    await user.click(screen.getByRole("button", { name: "Ingest text" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Ingest text" })).toBeDisabled(),
    );
    expect(screen.getByRole("button", { name: "Ingest URL" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();

    resolvePost(jsonResponse(201, DOC_A));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Ingest text" })).toBeEnabled(),
    );
  });
});