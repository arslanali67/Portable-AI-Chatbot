// Tests for widget.js's markdown rendering: bold (**text**) and bullet
// lists are parsed into safe, explicitly-constructed DOM nodes (never
// innerHTML) exactly once — at the SSE `end` event — never mid-stream.
//
// This file (packages/widget/) has no build step or test tooling of its
// own by design (see the widget's own header comment / architecture.md).
// It reuses the frontend app's already-installed Vitest+jsdom setup via
// vite.config.ts's `test.include`, and imports widget.js directly by
// relative path. widget.js exposes a small module.exports hook that is
// dead code in real browsers (`module` is never defined there) — see its
// end-of-file comment — purely so this suite can reach internal functions
// without a build step or a second copy of the file.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const WIDGET_PATH = "./widget.js";

function installScriptTag(publicKey = "pk_test", apiBase = "") {
  const script = document.createElement("script");
  script.src = "http://localhost/widget.js";
  script.setAttribute("data-chatbot", publicKey);
  script.setAttribute("data-api", apiBase);
  document.head.appendChild(script);
  return script;
}

// A controllable SSE body: the test decides exactly when each chunk (and
// the terminating "done") becomes visible to the reader, so DOM state can
// be inspected at precise points mid-stream — not just before/after the
// whole exchange.
function controlledSseBody() {
  const encoder = new TextEncoder();
  const queue = [];
  const waiting = [];
  function deliver(result) {
    if (waiting.length) {
      waiting.shift()(result);
    } else {
      queue.push(result);
    }
  }
  return {
    push(text) {
      deliver({ done: false, value: encoder.encode(text) });
    },
    finish() {
      deliver({ done: true, value: undefined });
    },
    getReader() {
      return {
        read() {
          if (queue.length) {
            return Promise.resolve(queue.shift());
          }
          return new Promise((resolve) => waiting.push(resolve));
        },
      };
    },
  };
}

function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function mockFetch(stream) {
  return vi.fn((input) => {
    const url = String(input);
    if (url.indexOf("/widget/config") !== -1) {
      return Promise.resolve({ ok: false });
    }
    if (url.indexOf("/widget/session") !== -1) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            session_token: "tok",
            config: { chatbot_name: "Bot", welcome_message: "hi" },
          }),
      });
    }
    if (url.indexOf("/chat/stream") !== -1) {
      return Promise.resolve({ ok: true, body: stream });
    }
    return Promise.reject(new Error("unexpected fetch: " + url));
  });
}

async function loadWidget() {
  vi.resetModules();
  return import(WIDGET_PATH);
}

beforeEach(() => {
  document.head.innerHTML = "";
  document.body.innerHTML = "";
  delete window.__portableAIWidgetLoaded;
  try {
    localStorage.clear();
  } catch (e) {
    // ignore
  }
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("widget.js — parseInlineMarkdown (pure)", () => {
  it("renders **bold** as a real <strong> element", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("This is **bold** text.");
    const div = document.createElement("div");
    div.appendChild(frag);

    const strong = div.querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong.textContent).toBe("bold");
    expect(div.textContent).toBe("This is bold text.");
  });

  it("renders a bullet list (- and *) as <ul><li> elements", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("- one\n* two\n- three");
    const div = document.createElement("div");
    div.appendChild(frag);

    const ul = div.querySelector("ul");
    expect(ul).not.toBeNull();
    const items = ul.querySelectorAll("li");
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toBe("one");
    expect(items[1].textContent).toBe("two");
    expect(items[2].textContent).toBe("three");
  });

  it("supports bold inside a bullet list item", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("- **important** item");
    const div = document.createElement("div");
    div.appendChild(frag);

    const strong = div.querySelector("li strong");
    expect(strong).not.toBeNull();
    expect(strong.textContent).toBe("important");
  });

  it("leaves plain text with no markdown syntax completely unaffected", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("Hi! How can I help?");
    const div = document.createElement("div");
    div.appendChild(frag);

    expect(div.querySelector("strong")).toBeNull();
    expect(div.querySelector("ul")).toBeNull();
    expect(div.textContent).toBe("Hi! How can I help?");
  });

  it("never produces a live <script> element or executable markup from literal HTML-like text", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown(
      'Here: <script>alert(1)</script> and <img src=x onerror="alert(2)">',
    );
    const div = document.createElement("div");
    div.appendChild(frag);

    // The literal characters are preserved as inert text (never innerHTML),
    // so no real <script>/<img> element and no onerror attribute exist.
    expect(div.querySelectorAll("script")).toHaveLength(0);
    expect(div.querySelectorAll("img")).toHaveLength(0);
    expect(div.querySelectorAll("[onerror]")).toHaveLength(0);
    expect(div.textContent).toContain("<script>alert(1)</script>");
  });
});

describe("widget.js — streaming integration (real SSE flow, no innerHTML anywhere)", () => {
  it("stays raw textContent during active streaming and parses exactly once, at `end`", async () => {
    installScriptTag();
    const stream = controlledSseBody();
    vi.stubGlobal("fetch", mockFetch(stream));
    const widget = await loadWidget();

    widget.sendMessage("what can you do?");
    await flush();
    await flush(); // let session init + first fetch settle

    const placeholder = widget.messagesEl.lastElementChild;
    expect(placeholder).not.toBeNull();

    stream.push('event: token\ndata: {"delta":"**bo"}\n\n');
    await flush();
    expect(placeholder.querySelector("strong")).toBeNull();
    expect(placeholder.textContent).toBe("**bo");

    stream.push('event: token\ndata: {"delta":"ld** and:"}\n\n');
    await flush();
    expect(placeholder.querySelector("strong")).toBeNull();
    expect(placeholder.textContent).toBe("**bold** and:");

    stream.push('event: token\ndata: {"delta":" \\n- a\\n- b"}\n\n');
    await flush();
    expect(placeholder.querySelector("ul")).toBeNull();
    expect(placeholder.textContent).toBe("**bold** and: \n- a\n- b");

    stream.push("event: end\ndata: {}\n\n");
    stream.finish();
    await flush();

    const strong = placeholder.querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong.textContent).toBe("bold");
    const ul = placeholder.querySelector("ul");
    expect(ul).not.toBeNull();
    expect(ul.querySelectorAll("li")).toHaveLength(2);
    // Never built via innerHTML at any point in the whole flow.
    expect(placeholder.innerHTML).not.toMatch(/&lt;|&amp;lt;/);
  });

  it("never interprets a literal <script> tag in the streamed content as HTML, start to finish", async () => {
    installScriptTag();
    const stream = controlledSseBody();
    vi.stubGlobal("fetch", mockFetch(stream));
    const widget = await loadWidget();

    widget.sendMessage("say something dangerous");
    await flush();
    await flush();

    const placeholder = widget.messagesEl.lastElementChild;

    stream.push(
      'event: token\ndata: {"delta":"Sure: <script>alert(1)</script> done"}\n\n',
    );
    await flush();
    // Mid-stream: still raw textContent, the tag is inert literal text.
    expect(placeholder.querySelectorAll("script")).toHaveLength(0);
    expect(placeholder.textContent).toContain("<script>alert(1)</script>");

    stream.push("event: end\ndata: {}\n\n");
    stream.finish();
    await flush();

    // After parsing: still no live <script> element anywhere.
    expect(placeholder.querySelectorAll("script")).toHaveLength(0);
    expect(document.querySelectorAll("script[data-chatbot]")).toHaveLength(1); // only the loader tag
  });
});
