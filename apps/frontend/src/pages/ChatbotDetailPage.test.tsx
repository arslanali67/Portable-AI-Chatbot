// Tests for the real ChatbotDetailPage: header rendering, the tab shell over
// the nested Chat/Knowledge/Widget routes, the not-found/error state, and
// the Back link. All API access (including the nested pages' own initial
// fetches) is mocked at the global fetch boundary.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import ChatbotDetailPage from "./ChatbotDetailPage";
import { jsonResponse } from "../test/helpers";
import type { Chatbot } from "../api/types";

const fetchMock = vi.fn<typeof fetch>();

const BOT: Chatbot = {
  id: 4746,
  organization_id: 4590,
  name: "Support Bot",
  slug: "support-bot",
  description: "Handles support questions.",
  system_prompt: "You are a support assistant.",
  welcome_message: "Hi, how can I help?",
  status: "active",
  visibility: "public",
  language: "en",
  provider_id: "fake",
  model_id: "fake-model-small",
  rag_enabled: true,
  rag_top_k: null,
  response_schema: null,
  tools: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

interface RouteOverrides {
  chatbot?: Response;
}

function route(overrides: RouteOverrides = {}) {
  fetchMock.mockImplementation(async (input) => {
    const path = String(input);
    if (/\/chatbots\/4746$/.test(path)) return overrides.chatbot ?? jsonResponse(200, BOT);
    if (path.endsWith("/conversations")) return jsonResponse(200, { items: [], total: 0, limit: 50, offset: 0 });
    if (path.endsWith("/knowledge/documents")) return jsonResponse(200, { items: [], total: 0 });
    if (path.endsWith("/widget-config")) return jsonResponse(404, { detail: "No widget configured" });
    return jsonResponse(404, { detail: "Not found" });
  });
}

function renderPage(initialEntry = "/organizations/4590/chatbots/4746") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/organizations/:organizationId/chatbots/:chatbotId/*"
          element={<ChatbotDetailPage />}
        />
        <Route path="/organizations/:organizationId" element={<div>Chatbots list page</div>} />
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

describe("ChatbotDetailPage", () => {
  it("shows a loading state until the chatbot loads", () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => undefined));

    renderPage();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders the chatbot header, tabs and Back link once loaded", async () => {
    route();

    renderPage();

    await screen.findByRole("heading", { name: "Support Bot" });
    expect(screen.getByText(/\/support-bot/)).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText(/fake\/fake-model-small/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Chat" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Knowledge" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Widget" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back" })).toHaveAttribute(
      "href",
      "/organizations/4590",
    );
  });

  it("shows the chat console by default", async () => {
    route();

    renderPage();

    await screen.findByText("Select or create a conversation to start chatting.");
  });

  it("navigates to the Knowledge tab and renders its content", async () => {
    route();
    const user = userEvent.setup();

    renderPage();
    await screen.findByRole("heading", { name: "Support Bot" });

    await user.click(screen.getByRole("link", { name: "Knowledge" }));

    await screen.findByText("Documents (0)");
  });

  it("navigates to the Widget tab and renders its content", async () => {
    route();
    const user = userEvent.setup();

    renderPage();
    await screen.findByRole("heading", { name: "Support Bot" });

    await user.click(screen.getByRole("link", { name: "Widget" }));

    await screen.findByText(/No public widget credential yet/);
  });

  it("shows an error and a way back when the chatbot fails to load", async () => {
    route({ chatbot: jsonResponse(404, { detail: "Chatbot not found" }) });

    renderPage();

    await screen.findByText("Chatbot not found");
    expect(screen.queryByRole("heading", { name: "Support Bot" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Chat" })).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("link", { name: "Back to chatbots" }));
    await screen.findByText("Chatbots list page");
  });
});
