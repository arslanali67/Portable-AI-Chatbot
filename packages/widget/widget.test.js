// Tests for widget.js's markdown rendering: bold (**text**), bullet lists,
// and [text](url) links are parsed into safe, explicitly-constructed DOM
// nodes (never innerHTML) exactly once — at the SSE `end` event — never
// mid-stream.
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

function mockFetch(stream, overrides = {}) {
  return vi.fn((input) => {
    const url = String(input);
    if (url.indexOf("/widget/config") !== -1) {
      if (overrides.config) {
        return overrides.config();
      }
      return Promise.resolve({ ok: false });
    }
    if (url.indexOf("/widget/faq") !== -1) {
      if (overrides.faq) {
        return overrides.faq();
      }
      return Promise.resolve({ ok: true });
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

  it("renders an https link as a real <a> with exact textContent/href and target/rel guardrails", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("See [docs](https://example.com/docs) for more.");
    const div = document.createElement("div");
    div.appendChild(frag);

    const link = div.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.textContent).toBe("docs");
    expect(link.getAttribute("href")).toBe("https://example.com/docs");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    // The raw URL never appears as visible text anywhere in the container.
    expect(div.textContent).not.toContain("https://example.com/docs");
    expect(div.textContent).toBe("See docs for more.");
  });

  it("neutralizes a javascript: link — plain text, no <a>, no javascript: substring anywhere", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("[click me](javascript:evil)");
    const div = document.createElement("div");
    div.appendChild(frag);

    expect(div.querySelector("a")).toBeNull();
    expect(div.textContent).toBe("click me");
    expect(div.innerHTML).not.toContain("javascript:");
  });

  it("neutralizes a data: link — plain text, no <a>, no data: substring anywhere", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("[x](data:text/html,evil)");
    const div = document.createElement("div");
    div.appendChild(frag);

    expect(div.querySelector("a")).toBeNull();
    expect(div.textContent).toBe("x");
    expect(div.innerHTML).not.toContain("data:");
  });

  it("renders a link inside a bullet list item with correct <li>/<a> structure", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("- [docs](https://example.com) for details");
    const div = document.createElement("div");
    div.appendChild(frag);

    const li = div.querySelector("ul li");
    expect(li).not.toBeNull();
    const link = li.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.textContent).toBe("docs");
    expect(link.getAttribute("href")).toBe("https://example.com");
    expect(li.textContent).toBe("docs for details");
  });

  it("renders a link nested inside bold text as a real <a> inside <strong>", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("**Read the [docs](https://example.com) now**");
    const div = document.createElement("div");
    div.appendChild(frag);

    const strong = div.querySelector("strong");
    expect(strong).not.toBeNull();
    const link = strong.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.textContent).toBe("docs");
    expect(link.getAttribute("href")).toBe("https://example.com");
    expect(strong.textContent).toBe("Read the docs now");
  });

  it("documented edge case: bold-looking syntax inside link text renders literally, not as <strong>", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("[**bold**](https://example.com)");
    const div = document.createElement("div");
    div.appendChild(frag);

    // A link's text portion is set via textContent directly and is never
    // recursively parsed, so "**bold**" shows up as the link's literal
    // label — no nested <strong> inside the <a>.
    const link = div.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.textContent).toBe("**bold**");
    expect(link.querySelector("strong")).toBeNull();
  });

  it("resolves a Wikipedia-style URL with an internal balanced paren to the complete href", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown(
      "[Example](https://en.wikipedia.org/wiki/Example_(disambiguation))",
    );
    const div = document.createElement("div");
    div.appendChild(frag);

    const link = div.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.getAttribute("href")).toBe(
      "https://en.wikipedia.org/wiki/Example_(disambiguation)",
    );
    expect(link.textContent).toBe("Example");
    // No trailing stray characters left over outside the <a>.
    expect(div.textContent).toBe("Example");
  });

  it("resolves a URL with multiple nested levels of parens to the complete href", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown(
      "[nested](https://example.com/foo(bar(baz)))",
    );
    const div = document.createElement("div");
    div.appendChild(frag);

    const link = div.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.getAttribute("href")).toBe("https://example.com/foo(bar(baz))");
    expect(link.textContent).toBe("nested");
    expect(div.textContent).toBe("nested");
  });

  it("autolinks a bare URL in plain text as a real <a> with href and label both equal to the URL", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("Visit https://2wordit.com/ today");
    const div = document.createElement("div");
    div.appendChild(frag);

    const link = div.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.getAttribute("href")).toBe("https://2wordit.com/");
    expect(link.textContent).toBe("https://2wordit.com/");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(div.textContent).toBe("Visit https://2wordit.com/ today");
  });

  it("excludes trailing sentence-ending punctuation from a bare-URL autolink (the reported real-world case)", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown(
      "The website for 2WordIT is https://2wordit.com/.",
    );
    const div = document.createElement("div");
    div.appendChild(frag);

    const link = div.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.getAttribute("href")).toBe("https://2wordit.com/");
    expect(link.textContent).toBe("https://2wordit.com/");
    // The trailing period is separate plain text right after the <a>, not
    // swallowed into the href/label and not dropped.
    expect(link.nextSibling).not.toBeNull();
    expect(link.nextSibling.textContent).toBe(".");
    expect(div.textContent).toBe("The website for 2WordIT is https://2wordit.com/.");
  });

  it("does not double-link an explicit [text](url) — only one <a>, with the custom label, not the bare URL", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("Visit [our site](https://2wordit.com/) today");
    const div = document.createElement("div");
    div.appendChild(frag);

    const links = div.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0].textContent).toBe("our site");
    expect(links[0].getAttribute("href")).toBe("https://2wordit.com/");
  });

  it("autolinks a bare URL inside a bullet list item", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("- see https://2wordit.com/ for details");
    const div = document.createElement("div");
    div.appendChild(frag);

    const li = div.querySelector("ul li");
    expect(li).not.toBeNull();
    const link = li.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.getAttribute("href")).toBe("https://2wordit.com/");
    expect(link.textContent).toBe("https://2wordit.com/");
  });

  it("autolinks a bare URL inside bold text as a real <a> nested inside <strong>", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("**Check https://2wordit.com/ now**");
    const div = document.createElement("div");
    div.appendChild(frag);

    const strong = div.querySelector("strong");
    expect(strong).not.toBeNull();
    const link = strong.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.getAttribute("href")).toBe("https://2wordit.com/");
    expect(link.textContent).toBe("https://2wordit.com/");
    expect(strong.textContent).toBe("Check https://2wordit.com/ now");
  });

  it("does not falsely match a URL-shaped string that lacks a real http(s):// prefix", async () => {
    installScriptTag();
    vi.stubGlobal("fetch", mockFetch(controlledSseBody()));
    const widget = await loadWidget();

    const frag = widget.parseInlineMarkdown("this contains :// but is not a url, and ftp://example.com isn't http(s) either");
    const div = document.createElement("div");
    div.appendChild(frag);

    expect(div.querySelector("a")).toBeNull();
    expect(div.textContent).toBe(
      "this contains :// but is not a url, and ftp://example.com isn't http(s) either",
    );
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

  it("stays raw textContent for a mid-stream partial link and parses only at `end`", async () => {
    installScriptTag();
    const stream = controlledSseBody();
    vi.stubGlobal("fetch", mockFetch(stream));
    const widget = await loadWidget();

    widget.sendMessage("share a link");
    await flush();
    await flush();

    const placeholder = widget.messagesEl.lastElementChild;

    stream.push('event: token\ndata: {"delta":"[Link Te"}\n\n');
    await flush();
    expect(placeholder.querySelector("a")).toBeNull();
    expect(placeholder.textContent).toBe("[Link Te");

    stream.push('event: token\ndata: {"delta":"xt](https://example.com)"}\n\n');
    await flush();
    expect(placeholder.querySelector("a")).toBeNull();
    expect(placeholder.textContent).toBe("[Link Text](https://example.com)");

    stream.push("event: end\ndata: {}\n\n");
    stream.finish();
    await flush();

    const link = placeholder.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.textContent).toBe("Link Text");
    expect(link.getAttribute("href")).toBe("https://example.com");
  });

  it("stays raw textContent for a mid-stream partial bare URL and parses only at `end`", async () => {
    installScriptTag();
    const stream = controlledSseBody();
    vi.stubGlobal("fetch", mockFetch(stream));
    const widget = await loadWidget();

    widget.sendMessage("share a bare url");
    await flush();
    await flush();

    const placeholder = widget.messagesEl.lastElementChild;

    stream.push('event: token\ndata: {"delta":"Visit https://2wor"}\n\n');
    await flush();
    expect(placeholder.querySelector("a")).toBeNull();
    expect(placeholder.textContent).toBe("Visit https://2wor");

    stream.push('event: token\ndata: {"delta":"dit.com/ today"}\n\n');
    await flush();
    expect(placeholder.querySelector("a")).toBeNull();
    expect(placeholder.textContent).toBe("Visit https://2wordit.com/ today");

    stream.push("event: end\ndata: {}\n\n");
    stream.finish();
    await flush();

    const link = placeholder.querySelector("a");
    expect(link).not.toBeNull();
    expect(link.getAttribute("href")).toBe("https://2wordit.com/");
    expect(link.textContent).toBe("https://2wordit.com/");
  });
});

describe("widget.js — preset/FAQ question chips", () => {
  it("renders suggestion chips from the eager config as soon as the panel first opens", async () => {
    installScriptTag();
    vi.stubGlobal(
      "fetch",
      mockFetch(controlledSseBody(), {
        config: () =>
          Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                chatbot_name: "Bot",
                welcome_message: "hi",
                preset_questions: [{ question: "What are your hours?", answer: "9-5, Mon-Fri." }],
              }),
          }),
      }),
    );
    const widget = await loadWidget();
    await flush();
    await flush();

    widget.launcherEl.click();
    await flush();

    const chip = Array.from(widget.panelEl.querySelectorAll("button")).find(
      (b) => b.textContent === "What are your hours?",
    );
    expect(chip).not.toBeUndefined();
  });

  it("clicking a chip renders the question+answer bubble pair instantly, before the persist call resolves", async () => {
    installScriptTag();
    localStorage.setItem("portableai_session_pk_test", "existing-session-tok");
    let resolveFaq;
    vi.stubGlobal(
      "fetch",
      mockFetch(controlledSseBody(), {
        faq: () => new Promise((resolve) => { resolveFaq = resolve; }),
      }),
    );
    const widget = await loadWidget();
    widget.setPresetQuestions([{ question: "Q1", answer: "**A1** bold" }]);

    widget.askPresetQuestion(0);
    // No await before this check: proves the bubble pair renders
    // synchronously from already-known data, not after a network round trip.
    const bubbles = widget.messagesEl.children;
    expect(bubbles.length).toBe(2);
    expect(bubbles[0].textContent).toBe("Q1");
    const strong = bubbles[1].querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong.textContent).toBe("A1");

    resolveFaq({ ok: true });
    await flush();
  });

  it("fires a background POST to /widget/faq with session_token and question_index once a session exists", async () => {
    installScriptTag("pk_test");
    localStorage.setItem("portableai_session_pk_test", "existing-session-tok");
    const fetchMock = mockFetch(controlledSseBody());
    vi.stubGlobal("fetch", fetchMock);
    const widget = await loadWidget();
    widget.setPresetQuestions([{ question: "Q1", answer: "A1" }]);

    widget.askPresetQuestion(0);
    await flush();

    const faqCall = fetchMock.mock.calls.find((c) => String(c[0]).indexOf("/widget/faq") !== -1);
    expect(faqCall).not.toBeUndefined();
    const body = JSON.parse(faqCall[1].body);
    expect(body.session_token).toBe("existing-session-tok");
    expect(body.question_index).toBe(0);
  });

  it("lazily creates a session first if none exists yet, then persists in the background", async () => {
    installScriptTag();
    const fetchMock = mockFetch(controlledSseBody());
    vi.stubGlobal("fetch", fetchMock);
    const widget = await loadWidget();
    widget.setPresetQuestions([{ question: "Q1", answer: "A1" }]);

    widget.askPresetQuestion(0);
    await flush();
    await flush();

    const sessionCall = fetchMock.mock.calls.find((c) => String(c[0]).indexOf("/widget/session") !== -1);
    const faqCall = fetchMock.mock.calls.find((c) => String(c[0]).indexOf("/widget/faq") !== -1);
    expect(sessionCall).not.toBeUndefined();
    expect(faqCall).not.toBeUndefined();
  });

  it("keeps a chip visible after it's clicked, never hidden or removed", async () => {
    installScriptTag();
    vi.stubGlobal(
      "fetch",
      mockFetch(controlledSseBody(), {
        config: () =>
          Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ preset_questions: [{ question: "Q1", answer: "A1" }] }),
          }),
      }),
    );
    const widget = await loadWidget();
    await flush();
    await flush();
    widget.launcherEl.click();
    await flush();

    const chip = Array.from(widget.panelEl.querySelectorAll("button")).find(
      (b) => b.textContent === "Q1",
    );
    expect(chip).not.toBeUndefined();
    chip.click();
    await flush();

    expect(document.body.contains(chip)).toBe(true);
  });
});
