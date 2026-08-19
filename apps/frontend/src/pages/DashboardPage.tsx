import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage, useAuth } from "../auth/AuthContext";
import type { Chatbot, Organization } from "../api/types";

interface OrgSummary extends Organization {
  chatbots: Chatbot[];
}

export default function DashboardPage() {
  const { user } = useAuth();
  const [orgs, setOrgs] = useState<OrgSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const list = await api.listOrganizations();
        const withBots = await Promise.all(
          list.map(async (org) => {
            try {
              const chatbots = await api.listChatbots(org.id);
              return { ...org, chatbots };
            } catch {
              return { ...org, chatbots: [] as Chatbot[] };
            }
          }),
        );
        if (!cancelled) setOrgs(withBots);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }

  const totalChatbots = orgs.reduce((sum, o) => sum + o.chatbots.length, 0);
  const activeChatbots = orgs.reduce(
    (sum, o) => sum + o.chatbots.filter((c) => c.status === "active").length,
    0,
  );

  return (
    <section>
      <h1>Dashboard</h1>
      {user && <p className="muted">Welcome, {user.full_name}.</p>}
      {error && <div className="error-box">{error}</div>}

      <div className="stat-grid">
        <div className="stat-card">
          <span className="stat-value">{orgs.length}</span>
          <span className="stat-label">Organizations</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{totalChatbots}</span>
          <span className="stat-label">Chatbots</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{activeChatbots}</span>
          <span className="stat-label">Active</span>
        </div>
      </div>

      <h2>Your organizations</h2>
      {orgs.length === 0 ? (
        <p className="muted">
          No organizations yet. <Link to="/organizations">Create one</Link>.
        </p>
      ) : (
        <ul className="card-list">
          {orgs.map((org) => (
            <li key={org.id}>
              <Link to={`/organizations/${org.id}`}>
                <strong>{org.name}</strong>
                <span className="muted">
                  {" "}
                  · {org.chatbots.length} chatbot{org.chatbots.length === 1 ? "" : "s"}
                </span>
              </Link>
              <Link className="button small" to={`/organizations/${org.id}`}>
                Open
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}