/* PortableAI embeddable chatbot widget — vanilla JS, no dependencies.
 * Load via: <script src="/widget.js" data-chatbot="PUBLIC_KEY" async></script>
 * Renders messages as plain text (textContent) — never innerHTML with untrusted content.
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

  var root = document.createElement("div");
  root.id = "portableai-widget-root";
  root.style.cssText =
    "position:fixed;bottom:20px;right:20px;z-index:2147483000;font-family:system-ui,sans-serif;";
  document.body.appendChild(root);

  var launcher = document.createElement("button");
  launcher.textContent = "Chat";
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
    "padding:12px 16px;background:#2563eb;color:#fff;font-weight:600;";
  header.textContent = "Chatbot";
  panel.appendChild(header);

  var messages = document.createElement("div");
  messages.id = "portableai-messages";
  messages.style.cssText =
    "flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;";
  panel.appendChild(messages);

  var form = document.createElement("form");
  form.style.cssText = "display:flex;gap:8px;padding:10px;border-top:1px solid #eee;";
  var input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Type a message...";
  input.style.cssText = "flex:1;padding:8px;border:1px solid #ddd;border-radius:6px;";
  form.appendChild(input);
  var send = document.createElement("button");
  send.textContent = "Send";
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

  function setBusy(busy) {
    send.disabled = busy;
    input.disabled = busy;
    send.textContent = busy ? "..." : "Send";
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
        header.textContent = data.config.chatbot_name || "Chatbot";
        renderMessage("assistant", data.config.welcome_message || "Hello!");
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
                placeholder.textContent = accumulated || placeholder.textContent;
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
    launcher.textContent = open ? "×" : "Chat";
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) {
      return;
    }
    sendMessage(text);
  });
})();
