// Tests for the real ChatbotsPage: list rendering, create/edit form state
// (including the "New chatbot after Edit" leak regression), lifecycle
// mutations (activate/archive/delete) and their busy/disabled states. All
// API access is mocked at the global fetch boundary.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import ChatbotsPage from "./ChatbotsPage";
import { jsonResponse } from "../test/helpers";
import type { Chatbot, ModelInfo, Provider } from "../api/types";

const fetchMock = vi.fn<typeof fetch>();

const PROVIDER_A: Provider = {
  provider_id: "fake-a",
  display_name: "Fake A",
  description: "",
  enabled: true,
  authentication_type: "none",
  compatibility_type: "fake",
  capabilities: ["text_generation"],
};

const PROVIDER_B: Provider = {
  provider_id: "fake-b",
  display_name: "Fake B",
  description: "",
  enabled: true,
  authentication_type: "none",
  compatibility_type: "fake",
  capabilities: ["text_generation"],
};

const MODEL_A_SMALL: ModelInfo = {
  provider_id: "fake-a",
  model_id: "fake-model-small",
  display_name: "Small A",
  context_window: 4096,
  max_output_tokens: 1024,
  enabled: true,
  capabilities: ["text_generation"],
};

const MODEL_B_SMALL: ModelInfo = {
  provider_id: "fake-b",
  model_id: "fake-model-b",
  display_name: "Small B",
  context_window: 4096,
  max_output_tokens: 1024,
  enabled: true,
  capabilities: ["text_generation"],
};

const BOT_DRAFT: Chatbot = {
  id: 1,
  organization_id: 4590,
  name: "Draft Bot",
  slug: "draft-bot",
  description: "Draft description",
  system_prompt: "You are a draft assistant.",
  welcome_message: "Hi from draft",
  status: "draft",
  visibility: "private",
  language: "en",
  provider_id: "fake-a",
  model_id: "fake-model-small",
  rag_enabled: true,
  rag_top_k: null,
  response_schema: null,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
};

const BOT_ACTIVE: Chatbot = {
  ...BOT_DRAFT,
  id: 2,
  name: "Active Bot",
  slug: "active-bot",
  status: "active",
};

interface RouteOverrides {
  listBots?: Response;
  listProviders?: Response;
  modelsByProvider?: Record<string, Response>;
  create?: Response;
  update?: Response;
  activate?: Response;
  archive?: Response;
  del?: Response;
}

function route(overrides: RouteOverrides = {}) {
  fetchMock.mockImplementation(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();

    const modelsMatch = path.match(/\/ai\/providers\/([^/]+)\/models$/);
    if (modelsMatch) {
      const providerId = modelsMatch[1];
      return overrides.modelsByProvider?.[providerId] ?? jsonResponse(200, [MODEL_A_SMALL]);
    }
    if (path.endsWith("/ai/providers")) {
      return overrides.listProviders ?? jsonResponse(200, [PROVIDER_A]);
    }
    if (path.endsWith("/activate")) {
      return overrides.activate ?? jsonResponse(200, { ...BOT_DRAFT, status: "active" });
    }
    if (path.endsWith("/archive")) {
      return overrides.archive ?? jsonResponse(200, { ...BOT_ACTIVE, status: "archived" });
    }
    if (/\/chatbots\/\d+$/.test(path)) {
      if (method === "PATCH") return overrides.update ?? jsonResponse(200, BOT_DRAFT);
      if (method === "DELETE") return overrides.del ?? jsonResponse(204, null);
    }
    if (path.endsWith("/chatbots")) {
      if (method === "POST") return overrides.create ?? jsonResponse(201, BOT_DRAFT);
      return overrides.listBots ?? jsonResponse(200, []);
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
  return render(
    <MemoryRouter initialEntries={["/organizations/4590"]}>
      <Routes>
        <Route path="/organizations/:organizationId" element={<ChatbotsPage />} />
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

describe("ChatbotsPage", () => {
  it("shows a loading state until chatbots and providers settle", async () => {
    const resolvers: Array<(response: Response) => void> = [];
    fetchMock.mockImplementation(
      () => new Promise<Response>((resolve) => { resolvers.push(resolve); }),
    );

    renderPage();

    expect(screen.getByText("Loading…")).toBeInTheDocument();

    resolvers.forEach((resolve) => resolve(jsonResponse(200, [])));
    await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
  });

  it("renders the chatbot table with status, provider and model", async () => {
    route({ listBots: jsonResponse(200, [BOT_DRAFT, BOT_ACTIVE]) });

    renderPage();

    await screen.findByText("Draft Bot");
    const row = screen.getByText("Active Bot").closest("tr") as HTMLElement;
    expect(within(row).getByText("active")).toBeInTheDocument();
    expect(within(row).getByText("fake-a")).toBeInTheDocument();
    expect(within(row).getByText("fake-model-small")).toBeInTheDocument();
  });

  it("shows the empty state when there are no chatbots", async () => {
    route();

    renderPage();

    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");
  });

  it("shows a load error instead of the table", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/chatbots")) return jsonResponse(500, { detail: "Chatbots failed" });
      if (path.endsWith("/ai/providers")) return jsonResponse(200, [PROVIDER_A]);
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText("Chatbots failed");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("opens the create form with blank fields", async () => {
    route();
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));

    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByLabelText("Slug")).toHaveValue("");
    expect(screen.getByLabelText("Description")).toHaveValue("");
    expect(screen.getByLabelText("System prompt")).toHaveValue("");
    expect(screen.getByLabelText("Welcome message")).toHaveValue("");
    expect(screen.getByLabelText("Language")).toHaveValue("en");
    expect(screen.getByLabelText("Visibility")).toHaveValue("private");
    expect(screen.getByLabelText("RAG enabled")).toBeChecked();
    expect(screen.getByLabelText("RAG top_k (blank = default)")).toHaveValue(null);
  });

  it("does not leak edited values into a subsequent New chatbot form (regression)", async () => {
    route({ listBots: jsonResponse(200, [BOT_DRAFT]) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByRole("heading", { name: "Edit Draft Bot" });
    expect(screen.getByLabelText("Name")).toHaveValue("Draft Bot");

    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "Temporarily Renamed");
    await user.clear(screen.getByLabelText("Description"));
    await user.type(screen.getByLabelText("Description"), "Temp description");

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "New chatbot" }));

    await screen.findByRole("heading", { name: "New chatbot" });
    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByLabelText("Slug")).toHaveValue("");
    expect(screen.getByLabelText("Description")).toHaveValue("");
    expect(screen.getByLabelText("System prompt")).toHaveValue("");
    expect(screen.getByLabelText("Welcome message")).toHaveValue("");
    expect(screen.getByLabelText("Language")).toHaveValue("en");
    expect(screen.getByLabelText("Visibility")).toHaveValue("private");
    expect(screen.queryByDisplayValue("Temporarily Renamed")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("Temp description")).not.toBeInTheDocument();
  });

  it("loads models for the selected provider and resets the selection on provider change", async () => {
    route({
      listProviders: jsonResponse(200, [PROVIDER_A, PROVIDER_B]),
      modelsByProvider: {
        "fake-a": jsonResponse(200, [MODEL_A_SMALL]),
        "fake-b": jsonResponse(200, [MODEL_B_SMALL]),
      },
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));

    await screen.findByRole("option", { name: "Small A" });
    expect(calls("GET", /\/ai\/providers\/fake-a\/models$/)).toHaveLength(1);

    await user.selectOptions(screen.getByLabelText("Model"), "fake-model-small");
    expect(screen.getByLabelText("Model")).toHaveValue("fake-model-small");

    await user.selectOptions(screen.getByLabelText("Provider"), "fake-b");

    await screen.findByRole("option", { name: "Small B" });
    expect(calls("GET", /\/ai\/providers\/fake-b\/models$/)).toHaveLength(1);
    expect(screen.getByLabelText("Model")).toHaveValue("");
  });

  it("creates a chatbot with the entered fields and reloads the list", async () => {
    route({ listBots: jsonResponse(200, []) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));
    await screen.findByRole("option", { name: "Small A" });

    await user.type(screen.getByLabelText("Name"), "New Bot");
    await user.type(screen.getByLabelText("Slug"), "new-bot");
    await user.selectOptions(screen.getByLabelText("Model"), "fake-model-small");

    const getCallsBefore = calls("GET", /\/chatbots$/).length;
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(calls("POST", /\/chatbots$/)).toHaveLength(1));
    const [, init] = calls("POST", /\/chatbots$/)[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      name: "New Bot",
      slug: "new-bot",
      provider_id: "fake-a",
      model_id: "fake-model-small",
    });

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Create" })).not.toBeInTheDocument(),
    );
    expect(calls("GET", /\/chatbots$/).length).toBeGreaterThan(getCallsBefore);
  });

  it("shows an error and keeps the form open when creation fails", async () => {
    route({
      listBots: jsonResponse(200, []),
      create: jsonResponse(409, { detail: "Slug already taken" }),
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));
    await screen.findByRole("option", { name: "Small A" });
    await user.type(screen.getByLabelText("Name"), "Dup Bot");
    await user.type(screen.getByLabelText("Slug"), "dup-bot");
    await user.selectOptions(screen.getByLabelText("Model"), "fake-model-small");

    await user.click(screen.getByRole("button", { name: "Create" }));

    await screen.findByText("Slug already taken");
    expect(screen.getByRole("button", { name: "Create" })).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Dup Bot");
  });

  it("saves edits to an existing chatbot and reloads the list", async () => {
    route({
      listBots: jsonResponse(200, [BOT_DRAFT]),
      update: jsonResponse(200, { ...BOT_DRAFT, name: "Renamed" }),
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByRole("heading", { name: "Edit Draft Bot" });

    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "Renamed");

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(calls("PATCH", /\/chatbots\/1$/)).toHaveLength(1));
    const [, init] = calls("PATCH", /\/chatbots\/1$/)[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({ name: "Renamed" });

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Edit Draft Bot" })).not.toBeInTheDocument(),
    );
  });

  it("shows an error and keeps the edit form open when saving fails", async () => {
    route({
      listBots: jsonResponse(200, [BOT_DRAFT]),
      update: jsonResponse(422, { detail: "Invalid provider" }),
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByRole("heading", { name: "Edit Draft Bot" });

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await screen.findByText("Invalid provider");
    expect(screen.getByRole("heading", { name: "Edit Draft Bot" })).toBeInTheDocument();
  });

  it("submits rag_enabled and a numeric rag_top_k on create", async () => {
    route({ listBots: jsonResponse(200, []) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));
    await screen.findByRole("option", { name: "Small A" });

    await user.type(screen.getByLabelText("Name"), "RAG Bot");
    await user.type(screen.getByLabelText("Slug"), "rag-bot");
    await user.selectOptions(screen.getByLabelText("Model"), "fake-model-small");
    // top_k is entered while RAG is still enabled (the input disables once
    // RAG is turned off); the typed value must still be submitted.
    await user.type(screen.getByLabelText("RAG top_k (blank = default)"), "7");
    await user.click(screen.getByLabelText("RAG enabled"));

    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(calls("POST", /\/chatbots$/)).toHaveLength(1));
    const [, init] = calls("POST", /\/chatbots$/)[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      rag_enabled: false,
      rag_top_k: 7,
    });
  });

  it("submits rag_top_k as null when left blank", async () => {
    route({ listBots: jsonResponse(200, []) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));
    await screen.findByRole("option", { name: "Small A" });

    await user.type(screen.getByLabelText("Name"), "Default Bot");
    await user.type(screen.getByLabelText("Slug"), "default-bot");
    await user.selectOptions(screen.getByLabelText("Model"), "fake-model-small");

    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(calls("POST", /\/chatbots$/)).toHaveLength(1));
    const [, init] = calls("POST", /\/chatbots$/)[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      rag_enabled: true,
      rag_top_k: null,
    });
  });

  it("submits a parsed response_schema object on create", async () => {
    route({ listBots: jsonResponse(200, []) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));
    await screen.findByRole("option", { name: "Small A" });

    await user.type(screen.getByLabelText("Name"), "Structured Bot");
    await user.type(screen.getByLabelText("Slug"), "structured-bot");
    await user.selectOptions(screen.getByLabelText("Model"), "fake-model-small");
    fireEvent.change(
      screen.getByLabelText("Response JSON schema (blank = free-text response)"),
      { target: { value: '{"type": "object", "required": ["answer"]}' } },
    );

    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(calls("POST", /\/chatbots$/)).toHaveLength(1));
    const [, init] = calls("POST", /\/chatbots$/)[0];
    expect(JSON.parse(String(init?.body)).response_schema).toEqual({
      type: "object",
      required: ["answer"],
    });
  });

  it("submits response_schema as null when left blank", async () => {
    route({ listBots: jsonResponse(200, []) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));
    await screen.findByRole("option", { name: "Small A" });

    await user.type(screen.getByLabelText("Name"), "Free Text Bot");
    await user.type(screen.getByLabelText("Slug"), "free-text-bot");
    await user.selectOptions(screen.getByLabelText("Model"), "fake-model-small");

    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(calls("POST", /\/chatbots$/)).toHaveLength(1));
    const [, init] = calls("POST", /\/chatbots$/)[0];
    expect(JSON.parse(String(init?.body)).response_schema).toBeNull();
  });

  it("rejects invalid JSON in the response schema field before submitting", async () => {
    route({ listBots: jsonResponse(200, []) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));
    await screen.findByRole("option", { name: "Small A" });

    await user.type(screen.getByLabelText("Name"), "Bad Schema Bot");
    await user.type(screen.getByLabelText("Slug"), "bad-schema-bot");
    await user.selectOptions(screen.getByLabelText("Model"), "fake-model-small");
    fireEvent.change(
      screen.getByLabelText("Response JSON schema (blank = free-text response)"),
      { target: { value: "{not valid json" } },
    );

    await user.click(screen.getByRole("button", { name: "Create" }));

    await screen.findByText("Response schema must be valid JSON.");
    expect(calls("POST", /\/chatbots$/)).toHaveLength(0);
  });

  it("loads an existing chatbot's response_schema into the edit form", async () => {
    route({
      listBots: jsonResponse(200, [
        { ...BOT_DRAFT, response_schema: { type: "object", required: ["x"] } },
      ]),
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");

    await user.click(screen.getByRole("button", { name: "Edit" }));

    const field = screen.getByLabelText(
      "Response JSON schema (blank = free-text response)",
    ) as HTMLTextAreaElement;
    expect(JSON.parse(field.value)).toEqual({ type: "object", required: ["x"] });
  });

  it("enforces the 1-20 bound on the RAG top_k input", async () => {
    route();
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));

    const topKInput = screen.getByLabelText("RAG top_k (blank = default)");
    expect(topKInput).toHaveAttribute("min", "1");
    expect(topKInput).toHaveAttribute("max", "20");
  });

  it("loads an existing chatbot's rag_enabled and rag_top_k into the edit form", async () => {
    route({ listBots: jsonResponse(200, [{ ...BOT_DRAFT, rag_enabled: false, rag_top_k: 12 }]) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByRole("heading", { name: "Edit Draft Bot" });

    expect(screen.getByLabelText("RAG enabled")).not.toBeChecked();
    expect(screen.getByLabelText("RAG top_k (blank = default)")).toHaveValue(12);
  });

  it("activates a draft chatbot and reflects the refreshed status", async () => {
    let listCall = 0;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/ai/providers")) return jsonResponse(200, [PROVIDER_A]);
      if (path.endsWith("/ai/providers/fake-a/models")) return jsonResponse(200, [MODEL_A_SMALL]);
      if (path.endsWith("/activate")) return jsonResponse(200, { ...BOT_DRAFT, status: "active" });
      if (path.endsWith("/chatbots") && method === "GET") {
        listCall += 1;
        return jsonResponse(200, [listCall === 1 ? BOT_DRAFT : { ...BOT_DRAFT, status: "active" }]);
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");
    expect(screen.getByText("draft")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Activate" }));

    await waitFor(() => expect(screen.getByText("active")).toBeInTheDocument());
    expect(calls("POST", /\/activate$/)).toHaveLength(1);
  });

  it("archives an active chatbot and reflects the refreshed status", async () => {
    let listCall = 0;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/ai/providers")) return jsonResponse(200, [PROVIDER_A]);
      if (path.endsWith("/ai/providers/fake-a/models")) return jsonResponse(200, [MODEL_A_SMALL]);
      if (path.endsWith("/archive")) return jsonResponse(200, { ...BOT_ACTIVE, status: "archived" });
      if (path.endsWith("/chatbots") && method === "GET") {
        listCall += 1;
        return jsonResponse(200, [
          listCall === 1 ? BOT_ACTIVE : { ...BOT_ACTIVE, status: "archived" },
        ]);
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Active Bot");
    expect(screen.getByText("active")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Archive" }));

    await waitFor(() => expect(screen.getByText("archived")).toBeInTheDocument());
    expect(calls("POST", /\/archive$/)).toHaveLength(1);
  });

  it("asks for confirmation before deleting", async () => {
    route({ listBots: jsonResponse(200, [BOT_DRAFT]) });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(confirmSpy).toHaveBeenCalledWith('Delete chatbot "Draft Bot"? This cannot be undone.');
  });

  it("does not delete when the confirmation is dismissed", async () => {
    route({ listBots: jsonResponse(200, [BOT_DRAFT]) });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(calls("DELETE", /\/chatbots\/1$/)).toHaveLength(0);
  });

  it("deletes a chatbot after confirmation and refreshes the list", async () => {
    let listCall = 0;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/ai/providers")) return jsonResponse(200, [PROVIDER_A]);
      if (/\/chatbots\/\d+$/.test(path) && method === "DELETE") return jsonResponse(204, null);
      if (path.endsWith("/chatbots") && method === "GET") {
        listCall += 1;
        return jsonResponse(200, listCall === 1 ? [BOT_DRAFT] : []);
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");
    expect(calls("DELETE", /\/chatbots\/1$/)).toHaveLength(1);
  });

  it("disables the save button while a create request is in flight", async () => {
    let resolveCreate!: (response: Response) => void;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/ai/providers")) return jsonResponse(200, [PROVIDER_A]);
      if (path.endsWith("/ai/providers/fake-a/models")) return jsonResponse(200, [MODEL_A_SMALL]);
      if (path.endsWith("/chatbots") && method === "GET") return jsonResponse(200, []);
      if (path.endsWith("/chatbots") && method === "POST") {
        return new Promise<Response>((resolve) => { resolveCreate = resolve; });
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));
    await screen.findByRole("option", { name: "Small A" });
    await user.type(screen.getByLabelText("Name"), "New Bot");
    await user.type(screen.getByLabelText("Slug"), "new-bot");
    await user.selectOptions(screen.getByLabelText("Model"), "fake-model-small");

    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled());

    resolveCreate(jsonResponse(201, BOT_DRAFT));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Saving…" })).not.toBeInTheDocument(),
    );
  });

  it("disables the activate button for that row while the request is in flight", async () => {
    let resolveActivate!: (response: Response) => void;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/ai/providers")) return jsonResponse(200, [PROVIDER_A]);
      if (path.endsWith("/chatbots") && method === "GET") return jsonResponse(200, [BOT_DRAFT]);
      if (path.endsWith("/activate")) {
        return new Promise<Response>((resolve) => { resolveActivate = resolve; });
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");

    await user.click(screen.getByRole("button", { name: "Activate" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Activating…" })).toBeDisabled());

    resolveActivate(jsonResponse(200, { ...BOT_DRAFT, status: "active" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Activating…" })).not.toBeInTheDocument(),
    );
  });

  it("only sends one activate request even when clicked twice before the disabled state renders", async () => {
    let resolveActivate!: (response: Response) => void;
    let activateCalls = 0;
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/ai/providers")) return jsonResponse(200, [PROVIDER_A]);
      if (path.endsWith("/chatbots") && method === "GET") return jsonResponse(200, [BOT_DRAFT]);
      if (path.endsWith("/activate")) {
        activateCalls += 1;
        return new Promise<Response>((resolve) => { resolveActivate = resolve; });
      }
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();
    await screen.findByText("Draft Bot");

    const button = screen.getByRole("button", { name: "Activate" });
    // Synchronous double click, deliberately not awaiting a re-render between
    // clicks, to exercise the ref-based duplicate-submission guard rather
    // than just the (render-timing-dependent) disabled attribute.
    fireEvent.click(button);
    fireEvent.click(button);

    expect(activateCalls).toBe(1);

    resolveActivate(jsonResponse(200, { ...BOT_DRAFT, status: "active" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Activating…" })).not.toBeInTheDocument(),
    );
  });

  it("clears the activate busy state after a failed request", async () => {
    route({
      listBots: jsonResponse(200, [BOT_DRAFT]),
      activate: jsonResponse(500, { detail: "Activate failed" }),
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Draft Bot");

    await user.click(screen.getByRole("button", { name: "Activate" }));

    await screen.findByText("Activate failed");
    expect(screen.getByRole("button", { name: "Activate" })).toBeEnabled();
  });

  it("blocks submission and shows a validation error when no model is selected", async () => {
    route({ listBots: jsonResponse(200, []), listProviders: jsonResponse(200, []) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("No chatbots yet. Create one to configure a chatbot.");

    await user.click(screen.getByRole("button", { name: "New chatbot" }));
    await user.type(screen.getByLabelText("Name"), "No Provider Bot");
    await user.type(screen.getByLabelText("Slug"), "no-provider-bot");

    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(screen.getByText("Select a provider and a model.")).toBeInTheDocument();
    expect(calls("POST", /\/chatbots$/)).toHaveLength(0);
  });
});
