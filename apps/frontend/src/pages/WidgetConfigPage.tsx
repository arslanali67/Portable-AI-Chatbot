import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { api, API_BASE_URL } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { WidgetConfig } from "../api/types";

export default function WidgetConfigPage() {
  const { organizationId, chatbotId } = useParams<{
    organizationId: string;
    chatbotId: string;
  }>();
  const orgId = Number(organizationId);
  const botId = Number(chatbotId);

  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [originsText, setOriginsText] = useState("");
  const [working, setWorking] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .getWidgetConfig(orgId, botId)
      .then((cfg) => {
        setConfig(cfg);
        setOriginsText(cfg.allowed_origins.join("\n"));
      })
      .catch((err) => {
        if ((err as { status?: number }).status === 404) {
          setConfig(null);
        } else {
          setError(errorMessage(err));
        }
      })
      .finally(() => setLoading(false));
  }, [orgId, botId]);

  useEffect(load, [load]);

  async function createConfig(e: FormEvent) {
    e.preventDefault();
    setWorking(true);
    setError(null);
    try {
      const origins = originsText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      const created = await api.createWidgetConfig(orgId, botId, origins);
      setConfig({
        public_key: created.public_key,
        enabled: created.enabled,
        revoked_at: null,
        allowed_origins: origins,
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setWorking(false);
    }
  }

  async function revoke() {
    if (!window.confirm("Revoke this widget credential? The embed stops working immediately.")) {
      return;
    }
    setWorking(true);
    setError(null);
    try {
      await api.revokeWidgetConfig(orgId, botId);
      setConfig(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setWorking(false);
    }
  }

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }

  if (!config) {
    return (
      <div>
        <h2>Widget</h2>
        <p className="muted">
          No public widget credential yet. Create one to embed this chatbot on your site.
        </p>
        <form className="panel" onSubmit={createConfig}>
          <h3>Allowed origins (one per line)</h3>
          <textarea
            placeholder={"https://example.com"}
            value={originsText}
            onChange={(e) => setOriginsText(e.target.value)}
            rows={4}
          />
          <button type="submit" disabled={working}>
            {working ? "Creating…" : "Create widget credential"}
          </button>
        </form>
      </div>
    );
  }

  const script = `<script src="${widgetScriptSrc()}" data-chatbot="${config.public_key}" data-api="${widgetApiBase()}" async></script>`;

  return (
    <div>
      {error && <div className="error-box">{error}</div>}
      <div className="page-head">
        <h2>Widget</h2>
        <button className="button danger" onClick={revoke} disabled={working}>
          Revoke
        </button>
      </div>

      <div className="panel">
        <h3>Public key</h3>
        <code className="code-block">{config.public_key}</code>
        <p className="muted small">
          Enabled: {config.enabled ? "yes" : "no"}
          {config.revoked_at ? ` · revoked ${new Date(config.revoked_at).toLocaleString()}` : ""}
        </p>
      </div>

      <div className="panel">
        <h3>Embed snippet</h3>
        <p className="muted small">
          Place before <code>&lt;/body&gt;</code>. Serve <code>/widget.js</code> from your API host
          and set <code>data-api</code> to its base URL.
        </p>
        <pre className="code-block">{script}</pre>
      </div>

      <div className="panel">
        <h3>Preview</h3>
        <iframe
          title="Widget preview"
          className="widget-preview"
          srcDoc={previewHtml(config.public_key)}
        />
      </div>
    </div>
  );
}

function previewHtml(publicKey: string): string {
  return `<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><title>Widget preview</title></head>
<body>
  <p style="font-family:system-ui;color:#666;padding:16px">Preview pane — the launcher appears bottom-right.</p>
  <script src="${widgetScriptSrc()}" data-chatbot="${publicKey}" data-api="${widgetApiBase()}" async></script>
</body>
</html>`;
}

function widgetScriptSrc(): string {
  return API_BASE_URL ? `${API_BASE_URL}/widget.js` : "/widget.js";
}

function widgetApiBase(): string {
  return API_BASE_URL ? API_BASE_URL : window.location.origin;
}