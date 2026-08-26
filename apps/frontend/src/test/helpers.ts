// Shared fetch-boundary test helpers. Tests never call a real backend.

export function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (body === null ? "" : JSON.stringify(body)),
  } as unknown as Response;
}

export function sseResponse(chunks: string[]): Response {
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