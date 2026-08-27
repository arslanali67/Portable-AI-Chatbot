// Tests for the real ProvidersPage: provider/model discovery rendering,
// loading state, overall and per-provider failure tolerance, and the empty
// states. Fetch is mocked at the global boundary; no router/auth needed —
// the page is a pure read-only display over the AI management API.

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProvidersPage from "./ProvidersPage";
import { jsonResponse } from "../test/helpers";
import type { ModelInfo, Provider } from "../api/types";

const fetchMock = vi.fn<typeof fetch>();

const PROVIDER_A: Provider = {
  provider_id: "fake",
  display_name: "Fake Provider",
  description: "Deterministic offline provider.",
  enabled: true,
  authentication_type: "none",
  compatibility_type: "fake",
  capabilities: ["text_generation"],
};

const PROVIDER_B: Provider = {
  provider_id: "gemini",
  display_name: "Google Gemini",
  description: "OpenAI-compatible.",
  enabled: false,
  authentication_type: "api_key",
  compatibility_type: "openai_compatible",
  capabilities: ["text_generation", "streaming"],
};

const MODEL_A: ModelInfo = {
  provider_id: "fake",
  model_id: "fake-model-small",
  display_name: "Small",
  context_window: 4096,
  max_output_tokens: 1024,
  enabled: true,
  capabilities: ["text_generation"],
};

beforeEach(() => {
  localStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ProvidersPage", () => {
  it("shows a loading state until providers settle", async () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => undefined));

    render(<ProvidersPage />);

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders each provider with its models", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/ai/providers")) return jsonResponse(200, [PROVIDER_A]);
      if (path.endsWith("/ai/providers/fake/models")) return jsonResponse(200, [MODEL_A]);
      return jsonResponse(404, { detail: "Not found" });
    });

    render(<ProvidersPage />);

    await screen.findByText("Fake Provider");
    // One "enabled" badge for the provider, one for its model.
    expect(screen.getAllByText("enabled")).toHaveLength(2);
    expect(screen.getByText(/Small/)).toBeInTheDocument();
    expect(screen.getByText("4,096")).toBeInTheDocument();
    expect(screen.getByText("1,024")).toBeInTheDocument();
  });

  it("shows a disabled badge and no-models message for a provider with no models", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/ai/providers")) return jsonResponse(200, [PROVIDER_B]);
      if (path.endsWith("/ai/providers/gemini/models")) return jsonResponse(200, []);
      return jsonResponse(404, { detail: "Not found" });
    });

    render(<ProvidersPage />);

    await screen.findByText("Google Gemini");
    expect(screen.getByText("disabled")).toBeInTheDocument();
    expect(screen.getByText("No models.")).toBeInTheDocument();
  });

  it("tolerates one provider's model request failing without losing the others", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/ai/providers")) return jsonResponse(200, [PROVIDER_A, PROVIDER_B]);
      if (path.endsWith("/ai/providers/fake/models")) return jsonResponse(200, [MODEL_A]);
      if (path.endsWith("/ai/providers/gemini/models")) return jsonResponse(500, { detail: "boom" });
      return jsonResponse(404, { detail: "Not found" });
    });

    render(<ProvidersPage />);

    await screen.findByText("Fake Provider");
    expect(screen.getByText("Google Gemini")).toBeInTheDocument();
    expect(screen.getByText(/Small/)).toBeInTheDocument();
    // The failed provider falls back to an empty model list instead of
    // taking down the page.
    expect(screen.getByText("No models.")).toBeInTheDocument();
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
  });

  it("shows an error and no provider panels when the provider list itself fails", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/ai/providers")) return jsonResponse(500, { detail: "Providers unavailable" });
      return jsonResponse(404, { detail: "Not found" });
    });

    render(<ProvidersPage />);

    await screen.findByText("Providers unavailable");
    expect(screen.queryByText("Fake Provider")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AI Providers" })).toBeInTheDocument();
  });

  it("renders no panels and no error when there are simply no providers configured", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/ai/providers")) return jsonResponse(200, []);
      return jsonResponse(404, { detail: "Not found" });
    });

    render(<ProvidersPage />);

    await waitForNoLoading();
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
    expect(screen.queryAllByRole("table")).toHaveLength(0);
  });

  async function waitForNoLoading() {
    await screen.findByRole("heading", { name: "AI Providers" });
  }
});
