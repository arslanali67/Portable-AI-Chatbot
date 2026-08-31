// Tests for the real ChatConsolePage: conversation list/selection/creation,
// message history, optimistic send + SSE reconciliation (start/user/token/end/
// error contract of POST .../chat/stream), error and disabled states.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import ChatConsolePage from "./ChatConsolePage";
import { jsonResponse, sseResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

const CONV_A = {
  id: 11,
  organization_id: 4590,
  chatbot_id: 4746,
  user_id: 1,
  title: "Chat A",
  status: "active",
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
};

const CONV_B = { ...CONV_A, id: 12, title: "Chat B" };
const CONV_ARCHIVED = { ...CONV_A, id: 13, title: "Old Chat", status: "archived" };

const MSGS_A = [
  {
    id: 101,
    conversation_id: 11,
    role: "user",
    content: "hello there",
    sequence_number: 1,
    metadata: null,
    created_at: "2026-08-01T10:01:00Z",
  },
  {
    id: 102,
    conversation_id: 11,
    role: "assistant",
    content: "Hi! How can I help?",
    sequence_number: 2,
    metadata: null,
    created_at: "2026-08-01T10:01:05Z",
  },
];

const MSGS_B = [
  {
    id: 201,
    conversation_id: 12,
    role: "user",
    content: "beta msg",
    sequence_number: 1,
    metadata: null,
    created_at: "2026-08-02T10:00:00Z",
  },
];

function route(options: {
  list?: unknown[];
  messages?: Record<number, unknown[]>;
  create?: Response;
  stream?: Response | Promise<Response>;
  archive?: Response;
  update?: Response;
} = {}) {
  const { list = [], messages = {}, create, stream, archive, update } = options;
  fetchMock.mockImplementation(async (input, init) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.endsWith("/chat/stream")) {
      return stream ?? sseResponse(["event: end\ndata: {}\n\n"]);
    }
    if (/\/conversations\/\d+\/archive$/.test(path)) {
      return archive ?? jsonResponse(200, { ...CONV_A, status: "archived" });
    }
    if (/\/conversations\/\d+\/messages$/.test(path)) {
      const id = Number(path.match(/\/conversations\/(\d+)\/messages$/)?.[1]);
      return jsonResponse(200, { items: messages[id] ?? [], total: 0, limit: 100, offset: 0 });
    }
    if (/\/conversations\/\d+$/.test(path) && method === "PATCH") {
      return update ?? jsonResponse(200, { ...CONV_A, title: "Renamed" });
    }
    if (path.endsWith("/conversations")) {
      if (method === "POST") return create ?? jsonResponse(201, CONV_B);
      return jsonResponse(200, { items: list, total: list.length, limit: 100, offset: 0 });
    }
    return jsonResponse(404, { detail: "Not found" });
  });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/organizations/4590/chatbots/4746"]}>
      <Routes>
        <Route
          path="/organizations/:organizationId/chatbots/:chatbotId/*"
          element={<ChatConsolePage />}
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

describe("ChatConsolePage", () => {
  it("shows empty states when no conversations exist", async () => {
    route();

    renderPage();

    await screen.findByText("No conversations yet.");
    await screen.findByText(/Select or create a conversation to start chatting\./);
  });

  it("lists conversations and loads the selected conversation's messages", async () => {
    route({ list: [CONV_A, CONV_B], messages: { 11: MSGS_A } });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");
    await screen.findByText("Chat B");

    await user.click(screen.getByRole("button", { name: "Chat A" }));

    await screen.findByText("hello there");
    expect(screen.getByText("Hi! How can I help?")).toBeInTheDocument();
    expect(screen.getByText("user")).toBeInTheDocument();
    expect(screen.getByText("assistant")).toBeInTheDocument();

    const msgCall = fetchMock.mock.calls.find((c) =>
      /\/conversations\/11\/messages$/.test(String(c[0])),
    );
    expect(msgCall).toBeDefined();
  });

  it("shows the no-messages state for a fresh conversation", async () => {
    route({ list: [CONV_A], messages: {} });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");

    await user.click(screen.getByRole("button", { name: "Chat A" }));

    await screen.findByText("No messages yet. Say hello.");
  });

  it("switches conversations and swaps the rendered history", async () => {
    route({ list: [CONV_A, CONV_B], messages: { 11: MSGS_A, 12: MSGS_B } });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat B");

    await user.click(screen.getByRole("button", { name: "Chat A" }));
    await screen.findByText("hello there");

    await user.click(screen.getByRole("button", { name: "Chat B" }));
    await screen.findByText("beta msg");
    expect(screen.queryByText("hello there")).not.toBeInTheDocument();
  });

  it("creates a conversation with the entered title and selects it", async () => {
    const created = { ...CONV_B, id: 13, title: "Support" };
    route({ list: [CONV_A], create: jsonResponse(201, created), messages: { 13: [] } });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");

    await user.type(
      screen.getByPlaceholderText("New conversation title…"),
      "Support",
    );
    await user.click(screen.getByRole("button", { name: "New" }));

    await screen.findByText("Support");
    const postCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/conversations") && c[1]?.method === "POST",
    );
    expect(String(postCall?.[1]?.body)).toContain('"title":"Support"');
    // The new conversation is selected immediately -> its messages load.
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some((c) => /\/conversations\/13\/messages$/.test(String(c[0]))),
      ).toBe(true),
    );
  });

  it("defaults the conversation title when submitted blank", async () => {
    route({ list: [CONV_A], create: jsonResponse(201, { ...CONV_B, id: 14, title: "New chat" }) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");

    await user.click(screen.getByRole("button", { name: "New" }));

    await screen.findByText("New chat");
    const postCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/conversations") && c[1]?.method === "POST",
    );
    expect(String(postCall?.[1]?.body)).toContain('"title":"New chat"');
  });

  it("sends a message and renders streamed tokens until completion", async () => {
    route({
      list: [CONV_A],
      messages: { 11: [] },
      stream: sseResponse([
        'event: start\ndata: {"conversation_id":11}\n\n',
        'event: user\ndata: {"id":501,"content":"hello bot","sequence_number":1}\n\n',
        'event: token\ndata: {"delta":"He"}\n\n',
        'event: token\ndata: {"delta":"y"}\n\n',
        'event: end\ndata: {"message_id":601,"sequence_number":2}\n\n',
      ]),
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");
    await user.click(screen.getByRole("button", { name: "Chat A" }));
    await screen.findByText("No messages yet. Say hello.");

    await user.type(screen.getByPlaceholderText("Type a message…"), "hello bot");
    await user.click(screen.getByRole("button", { name: "Send" }));

    // Request contract.
    const streamCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).endsWith("/conversations/11/chat/stream"),
    );
    expect(streamCall).toBeDefined();
    expect(String(streamCall?.[1]?.body)).toContain('"content":"hello bot"');

    // Optimistic user bubble appears, then streamed assistant content accumulates.
    await screen.findByText("hello bot");
    await screen.findByText("Hey");

    // Completion keeps the accumulated answer and re-enables input.
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    expect(screen.getByText("Hey")).toBeInTheDocument();
    // The conversation list is refreshed after the turn.
    await waitFor(() =>
      expect(fetchMock.mock.calls.filter((c) => String(c[0]).endsWith("/conversations")).length)
        .toBeGreaterThanOrEqual(2),
    );
  });

  it("shows stream error events, drops the pending answer and re-enables input", async () => {
    route({
      list: [CONV_A],
      messages: { 11: [] },
      stream: sseResponse([
        'event: user\ndata: {"id":501,"content":"hi","sequence_number":1}\n\n',
        'event: token\ndata: {"delta":"par"}\n\n',
        'event: error\ndata: {"detail":"AI provider unavailable"}\n\n',
      ]),
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");
    await user.click(screen.getByRole("button", { name: "Chat A" }));

    await user.type(screen.getByPlaceholderText("Type a message…"), "hi");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByText("AI provider unavailable");
    // The partial assistant answer is removed; the user message remains.
    expect(screen.queryByText("par")).not.toBeInTheDocument();
    expect(screen.getByText("hi")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  });

  it("surfaces network failures during streaming", async () => {
    let rejectStream!: (error: Error) => void;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/chat/stream")) {
        return new Promise<Response>((_resolve, reject) => { rejectStream = reject; });
      }
      if (/\/conversations\/\d+\/messages$/.test(path)) {
        return jsonResponse(200, { items: [], total: 0, limit: 100, offset: 0 });
      }
      if (path.endsWith("/conversations")) {
        return jsonResponse(200, { items: [CONV_A], total: 1, limit: 100, offset: 0 });
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");
    await user.click(screen.getByRole("button", { name: "Chat A" }));
    await screen.findByPlaceholderText("Type a message…");

    await user.type(screen.getByPlaceholderText("Type a message…"), "hello");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(rejectStream).toBeDefined());
    rejectStream(new Error("network down"));
    await screen.findByText("network down");
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  });

  it("disables the composer while streaming", async () => {
    let resolveStream!: (response: Response) => void;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/chat/stream")) {
        return new Promise<Response>((resolve) => { resolveStream = resolve; });
      }
      if (/\/conversations\/\d+\/messages$/.test(path)) {
        return jsonResponse(200, { items: [], total: 0, limit: 100, offset: 0 });
      }
      if (path.endsWith("/conversations")) {
        return jsonResponse(200, { items: [CONV_A], total: 1, limit: 100, offset: 0 });
      }
      return jsonResponse(404, { detail: "Not found" });
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");
    await user.click(screen.getByRole("button", { name: "Chat A" }));
    await screen.findByPlaceholderText("Type a message…");

    await user.type(screen.getByPlaceholderText("Type a message…"), "slow question");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const input = screen.getByPlaceholderText("Type a message…") as HTMLInputElement;
    await waitFor(() => expect(input).toBeDisabled());
    expect(screen.getByRole("button", { name: "…" })).toBeDisabled();

    resolveStream(sseResponse(['event: end\ndata: {"message_id":9}\n\n']));
    await waitFor(() => {
      const send = screen.getByRole("button", { name: "Send" });
      expect(send).toBeEnabled();
      expect((screen.getByPlaceholderText("Type a message…") as HTMLInputElement).value).toBe("");
    });
  });

  it("does not submit empty messages", async () => {
    route({ list: [CONV_A], messages: { 11: [] } });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");
    await user.click(screen.getByRole("button", { name: "Chat A" }));
    await screen.findByPlaceholderText("Type a message…");

    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith("/chat/stream"))).toBe(false);
  });

  it("archives a conversation after confirmation and removes it from the default view", async () => {
    route({ list: [CONV_A] });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");

    await user.click(screen.getByRole("button", { name: "Archive" }));

    expect(confirmSpy).toHaveBeenCalledOnce();
    await waitFor(() => {
      const archiveCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).endsWith("/conversations/11/archive"),
      );
      expect(archiveCall).toBeDefined();
      expect(archiveCall?.[1]?.method).toBe("POST");
    });
    await waitFor(() => expect(screen.queryByText("Chat A")).not.toBeInTheDocument());
  });

  it("does not archive when the confirmation is dismissed", async () => {
    route({ list: [CONV_A] });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");

    await user.click(screen.getByRole("button", { name: "Archive" }));

    expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith("/conversations/11/archive"))).toBe(false);
    expect(screen.getByText("Chat A")).toBeInTheDocument();
  });

  it("renames a conversation via the inline control", async () => {
    route({ list: [CONV_A], update: jsonResponse(200, { ...CONV_A, title: "Renamed Chat" }) });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");

    await user.click(screen.getByRole("button", { name: "Rename" }));
    const editInput = screen.getByDisplayValue("Chat A");
    await user.clear(editInput);
    await user.type(editInput, "Renamed Chat");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith("/conversations/11") && c[1]?.method === "PATCH",
      );
      expect(patchCall).toBeDefined();
      expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ title: "Renamed Chat" });
    });
    await screen.findByText("Renamed Chat");
  });

  it("cancels rename without submitting", async () => {
    route({ list: [CONV_A] });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");

    await user.click(screen.getByRole("button", { name: "Rename" }));
    await screen.findByDisplayValue("Chat A");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("button", { name: "Chat A" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((c) => c[1]?.method === "PATCH")).toBe(false);
  });

  it("hides rename and archive controls for archived conversations", async () => {
    route({ list: [CONV_ARCHIVED] });
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByLabelText("Show archived"));

    await screen.findByText(/Old Chat/);
    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
  });

  it("hides archived conversations by default and reveals them via the toggle", async () => {
    route({ list: [CONV_A, CONV_ARCHIVED] });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Chat A");
    expect(screen.queryByText(/Old Chat/)).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Show archived"));

    await screen.findByText(/Old Chat/);
    expect(screen.getByText("Chat A")).toBeInTheDocument();
  });

  it("disables the message composer for a selected archived conversation", async () => {
    route({ list: [CONV_ARCHIVED], messages: { 13: [] } });
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByLabelText("Show archived"));
    await screen.findByText(/Old Chat/);

    await user.click(screen.getByRole("button", { name: /Old Chat/ }));

    await screen.findByText("This conversation is archived and can't receive new messages.");
    expect(screen.queryByPlaceholderText("Type a message…")).not.toBeInTheDocument();
  });
});