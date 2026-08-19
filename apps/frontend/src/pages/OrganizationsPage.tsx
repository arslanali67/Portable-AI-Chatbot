import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { Organization } from "../api/types";

export default function OrganizationsPage() {
  const navigate = useNavigate();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .listOrganizations()
      .then(setOrganizations)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const org = await api.createOrganization({ name, slug });
      setOrganizations((prev) => [...prev, org]);
      setName("");
      setSlug("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }

  return (
    <section>
      <h1>Organizations</h1>

      <form className="inline-form" onSubmit={onSubmit}>
        <input
          placeholder="Organization name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={255}
        />
        <input
          placeholder="slug"
          value={slug}
          onChange={(e) => setSlug(e.target.value.toLowerCase())}
          required
          pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
          maxLength={100}
        />
        <button type="submit" disabled={creating}>
          {creating ? "Creating…" : "Create"}
        </button>
      </form>

      {error && <div className="error-box">{error}</div>}

      {organizations.length === 0 ? (
        <p className="muted">No organizations yet. Create one to begin.</p>
      ) : (
        <ul className="card-list">
          {organizations.map((org) => (
            <li key={org.id}>
              <Link to={`/organizations/${org.id}`}>
                <strong>{org.name}</strong>
                <span className="muted">/{org.slug}</span>
              </Link>
              <button
                className="link-button"
                onClick={() => navigate(`/organizations/${org.id}`)}
              >
                Open
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}