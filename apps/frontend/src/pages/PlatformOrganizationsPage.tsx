import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { PlatformOrganizationSummary } from "../api/types";

const PAGE_SIZE = 50;

export default function PlatformOrganizationsPage() {
  const [items, setItems] = useState<PlatformOrganizationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback((atOffset: number) => {
    setLoading(true);
    api
      .listPlatformOrganizations(PAGE_SIZE, atOffset)
      .then((res) => {
        setItems(res.items);
        setTotal(res.total);
        setOffset(res.offset);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(0), [load]);

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }

  return (
    <section>
      <h1>Organizations</h1>
      {error && <div className="error-box">{error}</div>}

      {items.length === 0 ? (
        <p className="muted">No organizations on the platform yet.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Owner</th>
              <th>Members</th>
              <th>Chatbots</th>
              <th>Last activity</th>
              <th>Created</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((org) => (
              <tr key={org.id}>
                <td>
                  <Link to={`/platform-admin/organizations/${org.id}`}>
                    <strong>{org.name}</strong> <span className="muted">/{org.slug}</span>
                  </Link>
                </td>
                <td>{org.owner_email ?? <span className="muted">—</span>}</td>
                <td>{org.member_count}</td>
                <td>{org.chatbot_count}</td>
                <td>
                  {org.last_activity_at ? (
                    new Date(org.last_activity_at).toLocaleString()
                  ) : (
                    <span className="muted">never</span>
                  )}
                </td>
                <td>{new Date(org.created_at).toLocaleDateString()}</td>
                <td>
                  {org.disabled_at ? (
                    <span className="badge badge-disabled-org">Disabled</span>
                  ) : (
                    <span className="badge badge-active">Active</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="actions" style={{ marginTop: 16 }}>
        <button
          className="secondary"
          disabled={offset === 0}
          onClick={() => load(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </button>
        <button
          className="secondary"
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => load(offset + PAGE_SIZE)}
        >
          Next
        </button>
        <span className="muted small">
          {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`} of {total}
        </span>
      </div>
    </section>
  );
}
