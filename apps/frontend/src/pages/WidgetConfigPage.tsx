import { useCallback, useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { api, API_BASE_URL } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { WidgetConfig, WidgetPosition } from "../api/types";

const POSITION_OPTIONS: WidgetPosition[] = ["bottom_right", "bottom_left"];

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

  // Theme form state
  const [themeColor, setThemeColor] = useState("");
  const [widgetPosition, setWidgetPosition] = useState<WidgetPosition | "">("");
  const [themeSaving, setThemeSaving] = useState(false);
  const [themeError, setThemeError] = useState<string | null>(null);
  const [avatarUploading, setAvatarUploading] = useState(false);

  function syncThemeForm(cfg: WidgetConfig) {
    setThemeColor(cfg.theme_color ?? "");
    setWidgetPosition(cfg.widget_position ?? "");
  }

  const load = useCallback(() => {
    setLoading(true);
    api
      .getWidgetConfig(orgId, botId)
      .then((cfg) => {
        setConfig(cfg);
        setOriginsText(cfg.allowed_origins.join("\n"));
        syncThemeForm(cfg);
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
      setConfig(created);
      syncThemeForm(created);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setWorking(false);
    }
  }

  async function saveTheme(e: FormEvent) {
    e.preventDefault();
    setThemeSaving(true);
    setThemeError(null);
    try {
      const updated = await api.updateWidgetConfig(orgId, botId, {
        theme_color: themeColor.trim() === "" ? null : themeColor.trim(),
        widget_position: widgetPosition === "" ? null : widgetPosition,
      });
      setConfig(updated);
      syncThemeForm(updated);
    } catch (err) {
      setThemeError(errorMessage(err));
    } finally {
      setThemeSaving(false);
    }
  }

  async function uploadAvatar(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) {
      return;
    }
    setAvatarUploading(true);
    setThemeError(null);
    try {
      const updated = await api.uploadWidgetAvatar(orgId, botId, file);
      setConfig(updated);
    } catch (err) {
      setThemeError(errorMessage(err));
    } finally {
      setAvatarUploading(false);
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
        {error && <div className="error-box">{error}</div>}
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
        <h3>Theme &amp; branding</h3>
        {themeError && <div className="error-box">{themeError}</div>}
        <form onSubmit={saveTheme}>
          <div className="form-grid">
            <label>
              Theme color
              <input
                type="text"
                placeholder="#2563eb"
                pattern="^#[0-9a-fA-F]{6}$"
                value={themeColor}
                onChange={(e) => setThemeColor(e.target.value)}
              />
            </label>
            <label>
              Position
              <select
                value={widgetPosition}
                onChange={(e) => setWidgetPosition(e.target.value as WidgetPosition | "")}
              >
                <option value="">Default (bottom right)</option>
                {POSITION_OPTIONS.map((p) => (
                  <option key={p} value={p}>
                    {p === "bottom_right" ? "Bottom right" : "Bottom left"}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button type="submit" disabled={themeSaving}>
            {themeSaving ? "Saving…" : "Save theme"}
          </button>
        </form>

        <h3>Avatar</h3>
        {config.avatar_url && (
          <img
            className="widget-avatar-preview"
            src={`${widgetApiBase()}${config.avatar_url}`}
            alt="Widget avatar"
            width={48}
            height={48}
          />
        )}
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={uploadAvatar}
          disabled={avatarUploading}
        />
        {avatarUploading && <p className="muted small">Uploading…</p>}
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
          src={`/organizations/${orgId}/chatbots/${botId}/widget-preview?key=${encodeURIComponent(config.public_key)}`}
        />
      </div>
    </div>
  );
}

export function widgetScriptSrc(): string {
  return API_BASE_URL ? `${API_BASE_URL}/widget.js` : "/widget.js";
}

export function widgetApiBase(): string {
  return API_BASE_URL ? API_BASE_URL : window.location.origin;
}