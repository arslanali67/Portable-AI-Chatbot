import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { PlatformOrganizationDetail } from "../api/types";

export default function PlatformOrganizationDetailPage() {
  const { organizationId } = useParams<{ organizationId: string }>();
  const orgId = Number(organizationId);

  const [org, setOrg] = useState<PlatformOrganizationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [overrideTier, setOverrideTier] = useState("");
  const [overrideStatus, setOverrideStatus] = useState("");
  const [overriding, setOverriding] = useState(false);
  const [overrideResult, setOverrideResult] = useState<{ tier: string | null; status: string | null } | null>(
    null,
  );

  const load = useCallback(() => {
    setLoading(true);
    api
      .getPlatformOrganization(orgId)
      .then(setOrg)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, [orgId]);

  useEffect(load, [load]);

  async function onDisable(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const summary = await api.disablePlatformOrganization(orgId, message.trim() || null);
      setOrg((prev) => (prev ? { ...prev, ...summary } : prev));
      setMessage("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function onEnable() {
    setSubmitting(true);
    setError(null);
    try {
      const summary = await api.enablePlatformOrganization(orgId);
      setOrg((prev) => (prev ? { ...prev, ...summary } : prev));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function onOverride(e: FormEvent) {
    e.preventDefault();
    setOverriding(true);
    setError(null);
    try {
      const result = await api.overridePlatformSubscription(orgId, {
        tier: overrideTier.trim() || null,
        status: overrideStatus.trim() || null,
      });
      setOverrideResult(result);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setOverriding(false);
    }
  }

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }
  if (!org) {
    return <div className="error-box">{error ?? "Organization not found"}</div>;
  }

  return (
    <section>
      <div className="page-head">
        <h1>
          {org.name} <span className="muted">/{org.slug}</span>
        </h1>
        {org.disabled_at ? (
          <span className="badge badge-disabled-org">Disabled</span>
        ) : (
          <span className="badge badge-active">Active</span>
        )}
      </div>

      {error && <div className="error-box">{error}</div>}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-value">{org.member_count}</div>
          <div className="stat-label">Members</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{org.chatbot_count}</div>
          <div className="stat-label">Chatbots</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{org.message_count}</div>
          <div className="stat-label">Messages</div>
        </div>
      </div>

      <div className="panel">
        <h2>Access control</h2>
        {org.disabled_at ? (
          <>
            <p>
              Disabled since {new Date(org.disabled_at).toLocaleString()}.
              {org.disabled_message && (
                <>
                  {" "}
                  Message shown to visitors: <em>&ldquo;{org.disabled_message}&rdquo;</em>
                </>
              )}
            </p>
            <button className="secondary" disabled={submitting} onClick={onEnable}>
              {submitting ? "Enabling…" : "Enable organization"}
            </button>
          </>
        ) : (
          <form onSubmit={onDisable} className="form-grid">
            <label className="full">
              Message shown to widget visitors while disabled (optional)
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="This assistant is currently unavailable."
                maxLength={2000}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="danger" disabled={submitting}>
                {submitting ? "Disabling…" : "Disable organization"}
              </button>
            </div>
          </form>
        )}
      </div>

      <div className="panel">
        <h2>Subscription override</h2>
        <p className="muted small">
          Directly sets this organization's tier/status, bypassing Stripe entirely (e.g. to comp
          an account). A later real Stripe webhook overwrites this normally.
        </p>
        <form onSubmit={onOverride} className="inline-form">
          <input
            placeholder="Tier (e.g. pro, enterprise, or blank)"
            aria-label="Tier"
            value={overrideTier}
            onChange={(e) => setOverrideTier(e.target.value)}
          />
          <input
            placeholder="Status (e.g. active, canceled, or blank)"
            aria-label="Status"
            value={overrideStatus}
            onChange={(e) => setOverrideStatus(e.target.value)}
          />
          <button type="submit" disabled={overriding}>
            {overriding ? "Saving…" : "Set subscription"}
          </button>
        </form>
        {overrideResult && (
          <p className="muted small">
            Now: tier={overrideResult.tier ?? "none"}, status={overrideResult.status ?? "none"}
          </p>
        )}
      </div>

      <div className="panel">
        <h2>Members</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Joined</th>
            </tr>
          </thead>
          <tbody>
            {org.members.map((m) => (
              <tr key={m.email}>
                <td>{m.email}</td>
                <td>{m.role}</td>
                <td>{new Date(m.joined_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>Chatbots</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {org.chatbots.map((c) => (
              <tr key={c.slug}>
                <td>
                  {c.name} <span className="muted">/{c.slug}</span>
                </td>
                <td>
                  <span className={`badge badge-${c.status}`}>{c.status}</span>
                </td>
                <td>{new Date(c.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
