/* PortableAI embeddable chatbot widget — vanilla JS, no dependencies.
 * Load via: <script src="/widget.js" data-chatbot="PUBLIC_KEY" async></script>
 * Renders messages via safe, explicitly-constructed DOM nodes
 * (document.createElement + textContent/createTextNode) — a minimal
 * bold/bullet-list/link markdown parser (see parseInlineMarkdown) builds a
 * DocumentFragment the same way. Never innerHTML, never an HTML string
 * built from untrusted content, anywhere in this file.
 */
(function () {
  "use strict";
  if (window.__portableAIWidgetLoaded) {
    return; // duplicate initialization guard
  }
  window.__portableAIWidgetLoaded = true;

  var scripts = document.getElementsByTagName("script");
  var current = null;
  for (var i = scripts.length - 1; i >= 0; i--) {
    if (scripts[i].src && scripts[i].src.indexOf("widget.js") !== -1) {
      current = scripts[i];
      break;
    }
  }
  var publicKey = current ? current.getAttribute("data-chatbot") : "";
  var apiBase = (current && current.getAttribute("data-api")) || "";

  if (!publicKey) {
    return; // fail gracefully
  }

  var sessionKey = "portableai_session_" + publicKey;
  var sessionToken = null;
  try {
    sessionToken = localStorage.getItem(sessionKey);
  } catch (e) {
    sessionToken = null;
  }

  var STRINGS = {
    en: {
      placeholder: "Type a message...",
      send: "Send",
      launcherClosed: "Chat",
      launcherOpen: "×",
      defaultGreeting: "Hello!",
    },
    ur: {
      placeholder: "پیغام لکھیں...",
      send: "بھیجیں",
      launcherClosed: "چیٹ",
      launcherOpen: "×",
      defaultGreeting: "السلام علیکم!",
    },
  };
  var strings = STRINGS.en; // updated once the eager config fetch resolves

  var root = document.createElement("div");
  root.id = "portableai-widget-root";
  root.style.cssText =
    "position:fixed;bottom:20px;right:20px;z-index:2147483000;font-family:system-ui,sans-serif;";
  document.body.appendChild(root);

  var launcher = document.createElement("button");
  launcher.textContent = strings.launcherClosed;
  launcher.style.cssText =
    "width:56px;height:56px;border-radius:50%;border:none;background:#2563eb;color:#fff;font-size:14px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,0.25);";
  root.appendChild(launcher);

  var panel = document.createElement("div");
  panel.style.cssText =
    "display:none;position:fixed;bottom:90px;right:20px;width:360px;max-width:calc(100vw - 40px);height:480px;max-height:calc(100vh - 120px);background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,0.2);flex-direction:column;overflow:hidden;";
  root.appendChild(panel);

  var header = document.createElement("div");
  header.id = "portableai-header";
  header.style.cssText =
    "padding:12px 16px;background:#2563eb;color:#fff;font-weight:600;display:flex;align-items:center;gap:8px;";
  panel.appendChild(header);

  var headerAvatar = document.createElement("img");
  headerAvatar.id = "portableai-header-avatar";
  headerAvatar.alt = "";
  headerAvatar.style.cssText =
    "width:24px;height:24px;border-radius:50%;object-fit:cover;display:none;flex:none;";
  header.appendChild(headerAvatar);

  var headerText = document.createElement("span");
  headerText.textContent = "Chatbot";
  header.appendChild(headerText);

  var messages = document.createElement("div");
  messages.id = "portableai-messages";
  messages.style.cssText =
    "flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;";
  panel.appendChild(messages);

  var form = document.createElement("form");
  form.style.cssText = "display:flex;gap:8px;padding:10px;border-top:1px solid #eee;";
  var input = document.createElement("input");
  input.type = "text";
  input.placeholder = strings.placeholder;
  input.style.cssText = "flex:1;padding:8px;border:1px solid #ddd;border-radius:6px;";
  form.appendChild(input);
  var send = document.createElement("button");
  send.textContent = strings.send;
  send.style.cssText =
    "padding:8px 14px;border:none;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer;";
  form.appendChild(send);
  panel.appendChild(form);

  var open = false;

  function renderMessage(role, text) {
    var div = document.createElement("div");
    div.style.cssText =
      "max-width:80%;padding:8px 12px;border-radius:10px;white-space:pre-wrap;word-break:break-word;" +
      (role === "user"
        ? "align-self:flex-end;background:#2563eb;color:#fff;"
        : "align-self:flex-start;background:#f1f5f9;color:#111;");
    div.textContent = text; // XSS-safe: textContent, never innerHTML
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  function showError(text) {
    renderMessage("assistant", text);
  }

  var BULLET_LINE = /^[-*]\s+(.*)$/;
  var SAFE_URL_SCHEME = /^https?:\/\//i;
  // A bare autolink candidate: from "http(s)://" up to the next whitespace
  // (or end of text) — GFM-style. Trailing sentence punctuation is trimmed
  // off afterward by trimTrailingPunctuation, not by this regex itself.
  var BARE_URL = /^https?:\/\/\S+/i;
  // Trailing chars that are almost always sentence punctuation, not part of
  // a URL's own path, when they're the very last character of a bare-URL
  // match: ".", ",", "!", "?", ";", ":", quotes. Stripped greedily (handles
  // runs like "...?!"). A trailing ")" is only stripped when it's
  // unbalanced within the candidate (more ")" than "(" seen so far) — that
  // keeps an intentional, balanced path segment like ".../foo(bar)" intact
  // while still dropping a sentence's own wrapping paren, e.g.
  // "(see https://example.com)" -> link excludes the final ")".
  var TRAILING_PUNCT_CHARS = ".,!?;:'\"";
  function trimTrailingPunctuation(url) {
    while (url.length > 0) {
      var last = url.charAt(url.length - 1);
      if (TRAILING_PUNCT_CHARS.indexOf(last) !== -1) {
        url = url.slice(0, -1);
        continue;
      }
      if (last === ")") {
        var opens = (url.match(/\(/g) || []).length;
        var closes = (url.match(/\)/g) || []).length;
        if (closes > opens) {
          url = url.slice(0, -1);
          continue;
        }
      }
      break;
    }
    return url;
  }

  // Scans text left-to-right for **bold** spans, [text](url) links, and
  // bare http(s):// URLs, appending each piece to `parent` as a <strong>,
  // an <a>, or a plain text node — never innerHTML, never an HTML string.
  // A manual scan (not a regex split) so a link's URL can contain balanced
  // parentheses (e.g. Wikipedia-style "foo_(disambiguation)" URLs): "(" and
  // ")" inside the URL are depth-tracked, and only a ")" at depth 0 — the
  // one matching the link's own opening "(" — closes the link. A naive
  // "first )" match would truncate such URLs.
  //
  // Precedence for the ambiguous compositions this parser supports:
  //  - A link inside bold text (e.g. "**[text](url)**") works: bold content
  //    is recursed into via this same function, so a nested link survives
  //    and renders as a real <a>. A bracket that isn't part of a
  //    "[text](url)" shape (e.g. "**array[0]**") never matches, so it's
  //    just literal text inside the <strong> — no ambiguity.
  //  - Bold-looking syntax inside link text (e.g. "[**bold**](url)") does
  //    NOT render as bold: a link's label is set via .textContent directly
  //    and is never rescanned, so "**bold**" appears literally. This
  //    matches the spec requirement that a link's .textContent be exactly
  //    the "text" portion, verbatim.
  //  - A bare URL never double-matches inside an explicit [text](url):
  //    when the "[" branch below successfully matches a whole link, the
  //    scan's index jumps straight past it (i = j + 1), so the URL's own
  //    characters are never revisited by this same loop — there's no
  //    separate "is this URL already inside a link" check needed, the
  //    consumed range is simply never scanned again. A bare URL inside
  //    bold text is scanned the normal way, via the same recursive call
  //    used for links-inside-bold.
  function appendInlineSpans(parent, text) {
    var i = 0;
    var textStart = 0;

    function flushText(end) {
      if (end > textStart) {
        parent.appendChild(document.createTextNode(text.slice(textStart, end)));
      }
    }

    while (i < text.length) {
      if (text.charAt(i) === "*" && text.charAt(i + 1) === "*") {
        var closeIdx = text.indexOf("**", i + 2);
        if (closeIdx !== -1) {
          var inner = text.slice(i + 2, closeIdx);
          if (inner.length > 0 && inner.indexOf("\n") === -1 && inner.indexOf("*") === -1) {
            flushText(i);
            var strong = document.createElement("strong");
            appendInlineSpans(strong, inner);
            parent.appendChild(strong);
            i = closeIdx + 2;
            textStart = i;
            continue;
          }
        }
      } else if (text.charAt(i) === "[") {
        var closeBracket = text.indexOf("]", i + 1);
        if (closeBracket !== -1 && text.charAt(closeBracket + 1) === "(") {
          var linkText = text.slice(i + 1, closeBracket);
          if (linkText.length > 0 && linkText.indexOf("\n") === -1) {
            // Depth-track the URL portion: "(" increments, ")" decrements,
            // and only a ")" at depth 0 is the link's true closing paren.
            var depth = 1;
            var j = closeBracket + 2;
            while (j < text.length && depth > 0) {
              var ch = text.charAt(j);
              if (ch === "\n") {
                break;
              }
              if (ch === "(") {
                depth++;
              } else if (ch === ")") {
                depth--;
                if (depth === 0) {
                  break;
                }
              }
              j++;
            }
            if (depth === 0) {
              var url = text.slice(closeBracket + 2, j);
              if (url.length > 0) {
                flushText(i);
                if (SAFE_URL_SCHEME.test(url)) {
                  var a = document.createElement("a");
                  a.href = url;
                  a.target = "_blank";
                  a.rel = "noopener noreferrer";
                  a.textContent = linkText;
                  parent.appendChild(a);
                } else {
                  // Unsafe scheme (javascript:, data:, ...) — keep the
                  // label as inert text, never a clickable <a>, never
                  // dropped.
                  parent.appendChild(document.createTextNode(linkText));
                }
                i = j + 1;
                textStart = i;
                continue;
              }
            }
          }
        }
      } else if (text.charAt(i) === "h" || text.charAt(i) === "H") {
        var bareMatch = BARE_URL.exec(text.slice(i));
        if (bareMatch) {
          var bareUrl = trimTrailingPunctuation(bareMatch[0]);
          if (bareUrl.length > 0) {
            flushText(i);
            var bareLink = document.createElement("a");
            bareLink.href = bareUrl;
            bareLink.target = "_blank";
            bareLink.rel = "noopener noreferrer";
            bareLink.textContent = bareUrl; // displayed text is the URL itself, GFM-style
            parent.appendChild(bareLink);
            i = i + bareUrl.length;
            textStart = i;
            continue;
          }
        }
      }
      i++;
    }
    flushText(text.length);
  }

  // Minimal markdown -> safe DOM: bold (**text**), bullet lists (lines
  // starting with "- " or "* "), [text](url) links, and bare http(s)://
  // URLs (GFM-style autolinking) only. Returns a DocumentFragment built
  // entirely via document.createElement/createTextNode — the caller can
  // appendChild it directly. No other markdown constructs are recognized;
  // unrecognized syntax (headings, code, numbered lists, ...) is left as
  // literal text, matching today's behavior for anything this parser
  // doesn't handle.
  function parseInlineMarkdown(text) {
    var frag = document.createDocumentFragment();
    var lines = text.split("\n");
    var i = 0;
    while (i < lines.length) {
      if (BULLET_LINE.test(lines[i])) {
        var ul = document.createElement("ul");
        ul.style.cssText = "margin:4px 0;padding-left:20px;";
        while (i < lines.length && BULLET_LINE.test(lines[i])) {
          var li = document.createElement("li");
          appendInlineSpans(li, BULLET_LINE.exec(lines[i])[1]);
          ul.appendChild(li);
          i++;
        }
        frag.appendChild(ul);
      } else {
        var plain = [];
        while (i < lines.length && !BULLET_LINE.test(lines[i])) {
          plain.push(lines[i]);
          i++;
        }
        appendInlineSpans(frag, plain.join("\n"));
      }
    }
    return frag;
  }

  function setBusy(busy) {
    send.disabled = busy;
    input.disabled = busy;
    send.textContent = busy ? "..." : strings.send;
  }

  function initSession(cb) {
    var payload = { public_key: publicKey };
    try {
      payload.origin = window.location.origin;
    } catch (e) {}
    fetch(apiBase + "/api/v1/public/widget/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        if (!r.ok) {
          throw new Error("session");
        }
        return r.json();
      })
      .then(function (data) {
        sessionToken = data.session_token;
        try {
          localStorage.setItem(sessionKey, sessionToken);
        } catch (e) {}
        headerText.textContent = data.config.chatbot_name || "Chatbot";
        renderMessage("assistant", data.config.welcome_message || strings.defaultGreeting);
        cb(null);
      })
      .catch(function () {
        cb(new Error("Could not start chat"));
      });
  }

  function sendMessage(text) {
    if (!sessionToken) {
      initSession(function (err) {
        if (err) {
          showError(err.message);
          return;
        }
        sendMessage(text);
      });
      return;
    }
    renderMessage("user", text);
    input.value = "";
    setBusy(true);
    var placeholder = renderMessage("assistant", "");
    var accumulated = "";
    var payload = { session_token: sessionToken, content: text };
    try {
      payload.origin = window.location.origin;
    } catch (e) {}
    fetch(apiBase + "/api/v1/public/widget/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        if (!r.ok || !r.body) {
          throw new Error("stream");
        }
        var reader = r.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        function pump() {
          return reader.read().then(function (result) {
            if (result.done) {
              return;
            }
            buffer += decoder.decode(result.value, { stream: true });
            var blocks = buffer.split("\n\n");
            buffer = blocks.pop();
            blocks.forEach(function (block) {
              var lines = block.split("\n");
              var event = null;
              var dataStr = null;
              lines.forEach(function (line) {
                if (line.indexOf("event:") === 0) {
                  event = line.slice(6).trim();
                } else if (line.indexOf("data:") === 0) {
                  dataStr = line.slice(5).trim();
                }
              });
              if (!event || !dataStr) {
                return;
              }
              var data;
              try {
                data = JSON.parse(dataStr);
              } catch (e) {
                return;
              }
              if (event === "token" && data.delta) {
                accumulated += data.delta;
                placeholder.textContent = accumulated;
                messages.scrollTop = messages.scrollHeight;
              } else if (event === "error") {
                placeholder.textContent = data.detail || "Error";
              } else if (event === "end") {
                // Message is complete — parse once (never mid-stream) and
                // replace the raw accumulated text with safe, constructed
                // DOM nodes. Falls back to the placeholder's existing raw
                // text if the stream ended with nothing accumulated.
                var finalText = accumulated || placeholder.textContent;
                placeholder.textContent = "";
                placeholder.appendChild(parseInlineMarkdown(finalText));
              }
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function () {
        placeholder.textContent = "Connection error";
      })
      .then(function () {
        setBusy(false);
      });
  }

  launcher.addEventListener("click", function () {
    open = !open;
    panel.style.display = open ? "flex" : "none";
    launcher.textContent = open ? strings.launcherOpen : strings.launcherClosed;
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) {
      return;
    }
    sendMessage(text);
  });

  function applyPosition(position) {
    var isLeft = position === "bottom_left";
    root.style.left = isLeft ? "20px" : "";
    root.style.right = isLeft ? "" : "20px";
    panel.style.left = isLeft ? "20px" : "";
    panel.style.right = isLeft ? "" : "20px";
  }

  function applyTheme(config) {
    if (config.theme_color) {
      launcher.style.background = config.theme_color;
      header.style.background = config.theme_color;
      send.style.background = config.theme_color;
    }
    if (config.widget_position) {
      applyPosition(config.widget_position);
    }
    if (config.avatar_url) {
      headerAvatar.src = apiBase + config.avatar_url;
      headerAvatar.style.display = "inline-block";
    }
    strings = STRINGS[config.language] || STRINGS.en;
    input.placeholder = strings.placeholder;
    send.textContent = strings.send;
    if (!open) {
      launcher.textContent = strings.launcherClosed;
    }
    panel.setAttribute("dir", config.language === "ur" ? "rtl" : "ltr");
  }

  // Eager, session-less fetch so the always-visible launcher can theme
  // itself before the visitor ever interacts. No session is created here;
  // the lazy initSession()/first-message flow above is unrelated and unchanged.
  fetch(
    apiBase +
      "/api/v1/public/widget/config?public_key=" +
      encodeURIComponent(publicKey),
  )
    .then(function (r) {
      return r.ok ? r.json() : null;
    })
    .then(function (config) {
      if (config) {
        applyTheme(config);
      }
    })
    .catch(function () {
      // Fail silently — the widget still works with its built-in defaults.
    });

  // Test-only hook: `module` is never defined in a real browser (this file
  // is loaded as a plain <script>, not a CommonJS module), so this branch
  // is dead code in production and adds nothing to what ships. It exists
  // solely so the test suite (running under Node/Vitest) can reach
  // internal functions without a build step or a second copy of this file.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      parseInlineMarkdown: parseInlineMarkdown,
      renderMessage: renderMessage,
      sendMessage: sendMessage,
      messagesEl: messages,
    };
  }
})();
