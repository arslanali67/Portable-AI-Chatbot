// Tests for the real WidgetPreviewPage: script injection with the correct
// data-chatbot/data-api attributes, cleanup on unmount and on key change (no
// leaked/duplicated <script> tags), and the missing-key state. This page
// drives the customer-facing widget embed, so injection/cleanup correctness
// matters most.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";

import WidgetPreviewPage from "./WidgetPreviewPage";

function renderPreview(search = "?key=pk_abc123") {
  return render(
    <MemoryRouter initialEntries={[`/preview${search}`]}>
      <Routes>
        <Route path="/preview" element={<WidgetPreviewPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function scripts(): HTMLScriptElement[] {
  return Array.from(document.querySelectorAll("script[data-chatbot]"));
}

beforeEach(() => {
  document.querySelectorAll("script[data-chatbot]").forEach((s) => s.remove());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WidgetPreviewPage", () => {
  it("injects the widget script with the public key and api base", () => {
    renderPreview("?key=pk_abc123");

    expect(screen.getByText("Preview pane — the launcher appears bottom-right.")).toBeInTheDocument();

    const injected = scripts();
    expect(injected).toHaveLength(1);
    expect(injected[0].src).toContain("/widget.js");
    expect(injected[0].getAttribute("data-chatbot")).toBe("pk_abc123");
    expect(injected[0].getAttribute("data-api")).toBe(window.location.origin);
    expect(injected[0].async).toBe(true);
  });

  it("shows the missing-key message and injects no script when the key is absent", () => {
    renderPreview("");

    expect(screen.getByText("Missing widget key.")).toBeInTheDocument();
    expect(scripts()).toHaveLength(0);
  });

  it("removes the injected script on unmount", () => {
    const { unmount } = renderPreview("?key=pk_abc123");
    expect(scripts()).toHaveLength(1);

    unmount();

    expect(scripts()).toHaveLength(0);
  });

  it("does not leak or duplicate scripts when the key changes on the same mounted page", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/preview?key=pk_first"]}>
        <Routes>
          <Route
            path="/preview"
            element={
              <>
                <Link to="/preview?key=pk_second">switch key</Link>
                <WidgetPreviewPage />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(scripts()).toHaveLength(1);
    expect(scripts()[0].getAttribute("data-chatbot")).toBe("pk_first");

    // Real in-place navigation (same route, new search params) rather than a
    // remount, so this exercises the effect's cleanup-then-rerun path.
    await user.click(screen.getByRole("link", { name: "switch key" }));

    const remaining = scripts();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].getAttribute("data-chatbot")).toBe("pk_second");
  });
});
