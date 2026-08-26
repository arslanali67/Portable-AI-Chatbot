// Tests for the real streamChat() implementation: fetch + ReadableStream SSE
// parsing with "\n\n" frame buffering. fetch is mocked at the global boundary.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setToken, streamChat } from "./client";
import type { StreamEvent } from "./types";
import { jsonResponse } from "../test/helpers";

const fetchMock = vi.fn<typeof fetch>();

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  let index = 0;
  const body = {
    getReader() {
      return {
        read: async () => {
          if (index < chunks.length) {
            const value = encoder.encode(chunks[index]);
            index += 1;
            return { done: false, value };
          }
          return { done: true, value: undefined };
        },
      };
    },
  };
  return { ok: true, status: 200, body } as unknown as Response;
}

async function collect(content: string, response: Response): Promise<StreamEvent[]> {
  fetchMock.mockResolvedValue(response);
  const events: StreamEvent[] = [];
  await streamChat(4590, 1234, content, (event) => events.push(event));
  return events;
}

beforeEach(() => {
  localStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamChat", () => {
  it("POSTs to the conversation chat/stream endpoint with the content", async () => {
    await collect("hi", sseResponse(["event: end\ndata: {}\n\n"]));

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organizations/4590/conversations/1234/chat/stream");
    expect(init.method).toBe("POST");
    expect(String(init.body)).toContain('"content":"hi"');
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("emits multiple parsed SSE events in order", async () => {
    const events = await collect(
      "hi",
      sseResponse([
        'event: start\ndata: {"provider_id":"gemini"}\n\n',
        'event: token\ndata: {"delta":"Hello"}\n\nevent: token\ndata: {"delta":" world"}\n\n',
        'event: end\ndata: {"message_id":99}\n\n',
      ]),
    );

    expect(events.map((e) => e.type)).toEqual(["start", "token", "token", "end"]);
    expect(events[1]?.data.delta).toBe("Hello");
    expect(events[3]?.data.message_id).toBe(99);
  });

  it("buffers frames that arrive split across chunks", async () => {
    const events = await collect(
      "hi",
      sseResponse(['event: tok', 'en\ndata: {"delta":"Hi"}\n\n']),
    );

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: "token", data: { delta: "Hi" } });
  });

  it("skips malformed frames and falls back to an empty object for invalid JSON data", async () => {
    const events = await collect(
      "hi",
      sseResponse([
        'data: {"delta":"orphan"}\n\n', // missing event line -> ignored
        'event: token\n\n', // missing data line -> ignored
        'event: token\ndata: not-json\n\n', // invalid JSON -> data {}
        'noise\nmore\nevent: end\ndata: {}\n\n',
      ]),
    );

    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ type: "token", data: {} });
    expect(events[1]).toEqual({ type: "end", data: {} });
  });

  it("ignores non-SSE sentinel lines such as [DONE] (not part of this contract)", async () => {
    const events = await collect(
      "hi",
      sseResponse(['event: token\ndata: {"delta":"a"}\n\n[DONE]\n\nevent: end\ndata: {}\n\n']),
    );

    expect(events.map((e) => e.type)).toEqual(["token", "end"]);
  });

  it("sends the Authorization header when a token is stored", async () => {
    setToken("tok123");

    await collect("hi", sseResponse(["event: end\ndata: {}\n\n"]));

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer tok123");
  });

  it("rejects HTTP error responses via the shared error normalization", async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, { detail: "Streaming failed" }));

    const events: StreamEvent[] = [];
    await expect(streamChat(1, 2, "hi", (e) => events.push(e))).rejects.toMatchObject({
      status: 500,
      message: "Streaming failed",
    });
    expect(events).toHaveLength(0);
  });

  it("rejects when the response has no readable body", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200 } as unknown as Response);

    await expect(streamChat(1, 2, "hi", () => undefined)).rejects.toThrow(
      "Streaming not supported",
    );
  });

  it("propagates network failures", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));

    await expect(streamChat(1, 2, "hi", () => undefined)).rejects.toThrow("network down");
  });

  it("propagates mid-stream abort errors", async () => {
    const encoder = new TextEncoder();
    let reads = 0;
    const body = {
      getReader() {
        return {
          read: async () => {
            reads += 1;
            if (reads === 1) {
              return { done: false, value: encoder.encode('event: token\ndata: {"delta":"a"}\n\n') };
            }
            const error = new Error("The operation was aborted");
            error.name = "AbortError";
            throw error;
          },
        };
      },
    };
    fetchMock.mockResolvedValue({ ok: true, status: 200, body } as unknown as Response);

    const error = await streamChat(1, 2, "hi", () => undefined).then(
      () => null,
      (e) => e,
    );

    expect((error as Error).name).toBe("AbortError");
    expect(reads).toBeGreaterThan(1);
  });
});