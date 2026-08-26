// Shared fetch-boundary test helpers. Tests never call a real backend.

export function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (body === null ? "" : JSON.stringify(body)),
  } as unknown as Response;
}