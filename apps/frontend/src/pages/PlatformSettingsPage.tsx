import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { StripeCredentialStatus } from "../api/types";

export default function PlatformSettingsPage() {
  const [status, setStatus] = useState<StripeCredentialStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [secretKey, setSecretKey] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .getStripeSettings()
      .then(setStatus)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  async function save() {
    if (!secretKey.trim()) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const next = await api.setStripeSettings(secretKey.trim());
      setStatus(next);
      setSecretKey("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }

  return (
    <section>
      <h1>Settings</h1>

      <div className="panel">
        <h2>Stripe</h2>
        <p className="muted small">
          Platform-wide Stripe secret key used for all organizations' billing. Never shown again
          after saving — only the last 4 characters.
        </p>
        {error && <div className="error-box">{error}</div>}
        {status ? (
          <span className="muted small">
            {status.masked_key} · updated by {status.updated_by_email ?? "unknown"} on{" "}
            {new Date(status.updated_at).toLocaleDateString()}
          </span>
        ) : (
          <span className="muted small">No Stripe key configured yet.</span>
        )}
        <div className="inline-form">
          <input
            type="password"
            placeholder={status ? "New secret key to replace" : "Stripe secret key (sk_...)"}
            aria-label="Stripe secret key"
            value={secretKey}
            onChange={(e) => setSecretKey(e.target.value)}
          />
          <button onClick={save} disabled={saving || !secretKey.trim()}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </section>
  );
}
