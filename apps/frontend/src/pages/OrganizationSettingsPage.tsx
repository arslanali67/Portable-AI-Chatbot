import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage, useAuth } from "../auth/AuthContext";
import type {
  AICredentialStatus,
  Membership,
  MembershipRole,
  Organization,
  Provider,
} from "../api/types";

const ROLE_OPTIONS: MembershipRole[] = ["member", "admin", "owner"];

export default function OrganizationSettingsPage() {
  const { organizationId } = useParams<{ organizationId: string }>();
  const orgId = Number(organizationId);
  const navigate = useNavigate();
  const { user } = useAuth();

  const [organization, setOrganization] = useState<Organization | null>(null);
  const [members, setMembers] = useState<Membership[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");

  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState<MembershipRole>("member");

  // Tracks in-flight per-member mutations by a stable key (e.g. "remove:12").
  // The ref guards against duplicate submissions synchronously (before React
  // has re-rendered the disabled button); the state drives the UI.
  const pendingRef = useRef<Set<string>>(new Set());
  const [pendingActions, setPendingActions] = useState<Set<string>>(new Set());

  function isPending(key: string): boolean {
    return pendingActions.has(key);
  }

  function beginPending(key: string): boolean {
    if (pendingRef.current.has(key)) {
      return false;
    }
    pendingRef.current.add(key);
    setPendingActions((prev) => new Set(prev).add(key));
    return true;
  }

  function endPending(key: string) {
    pendingRef.current.delete(key);
    setPendingActions((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  }

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.getOrganization(orgId), api.listMembers(orgId)])
      .then(([org, memberList]) => {
        setOrganization(org);
        setName(org.name);
        setMembers(memberList);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, [orgId]);

  useEffect(load, [load]);

  const viewerMembership = members.find((m) => m.user_id === user?.id) ?? null;
  const viewerIsAdmin =
    viewerMembership?.role === "owner" || viewerMembership?.role === "admin";
  const viewerIsOwner = viewerMembership?.role === "owner";

  const [providers, setProviders] = useState<Provider[]>([]);
  const [credentials, setCredentials] = useState<AICredentialStatus[]>([]);
  const [credError, setCredError] = useState<string | null>(null);
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!viewerIsAdmin) {
      return;
    }
    Promise.all([api.listProviders(), api.listAiCredentials(orgId)])
      .then(([provs, creds]) => {
        setProviders(provs);
        setCredentials(creds);
      })
      .catch((err) => setCredError(errorMessage(err)));
  }, [viewerIsAdmin, orgId]);

  async function saveCredential(providerId: string) {
    const key = `cred:${providerId}`;
    if (!beginPending(key)) {
      return;
    }
    setCredError(null);
    try {
      const status = await api.setAiCredential(orgId, providerId, keyDrafts[providerId] ?? "");
      setCredentials((prev) => [...prev.filter((c) => c.provider_id !== providerId), status]);
      setKeyDrafts((prev) => ({ ...prev, [providerId]: "" }));
    } catch (err) {
      setCredError(errorMessage(err));
    } finally {
      endPending(key);
    }
  }

  async function removeCredential(providerId: string) {
    if (
      !window.confirm(
        `Remove the BYOK key for ${providerId}? Requests will fall back to the platform-shared key.`,
      )
    ) {
      return;
    }
    const key = `cred:${providerId}`;
    if (!beginPending(key)) {
      return;
    }
    setCredError(null);
    try {
      await api.removeAiCredential(orgId, providerId);
      setCredentials((prev) => prev.filter((c) => c.provider_id !== providerId));
    } catch (err) {
      setCredError(errorMessage(err));
    } finally {
      endPending(key);
    }
  }

  async function rename(e: FormEvent) {
    e.preventDefault();
    if (!beginPending("rename")) {
      return;
    }
    setError(null);
    try {
      const updated = await api.updateOrganization(orgId, { name });
      setOrganization(updated);
      setName(updated.name);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      endPending("rename");
    }
  }

  async function removeOrganization() {
    if (!organization) {
      return;
    }
    if (
      !window.confirm(
        `Delete organization "${organization.name}"? This permanently removes all of its ` +
          `chatbots, conversations, and knowledge. This cannot be undone.`,
      )
    ) {
      return;
    }
    if (!beginPending("delete")) {
      return;
    }
    setError(null);
    try {
      await api.deleteOrganization(orgId);
      navigate("/organizations");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      endPending("delete");
    }
  }

  async function addMember(e: FormEvent) {
    e.preventDefault();
    if (!beginPending("add")) {
      return;
    }
    setError(null);
    try {
      const member = await api.addMember(orgId, { email: newEmail.trim(), role: newRole });
      setMembers((prev) => [...prev, member]);
      setNewEmail("");
      setNewRole("member");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      endPending("add");
    }
  }

  async function changeRole(member: Membership, role: MembershipRole) {
    const key = `role:${member.id}`;
    if (!beginPending(key)) {
      return;
    }
    setError(null);
    try {
      const updated = await api.updateMemberRole(orgId, member.id, role);
      setMembers((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      endPending(key);
    }
  }

  async function removeMember(member: Membership) {
    const key = `remove:${member.id}`;
    if (pendingRef.current.has(key)) {
      return;
    }
    const isSelf = member.user_id === user?.id;
    const confirmed = window.confirm(
      isSelf
        ? "Leave this organization? You will lose access immediately."
        : `Remove ${member.user_full_name} from this organization?`,
    );
    if (!confirmed) {
      return;
    }
    if (!beginPending(key)) {
      return;
    }
    setError(null);
    try {
      await api.removeMember(orgId, member.id);
      if (isSelf) {
        navigate("/organizations");
        return;
      }
      setMembers((prev) => prev.filter((m) => m.id !== member.id));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      endPending(key);
    }
  }

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }

  if (!organization) {
    return (
      <section>
        <div className="error-box">{error}</div>
      </section>
    );
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>{organization.name}</h1>
          <p className="muted">/{organization.slug} · Settings</p>
        </div>
        <div className="actions">
          <Link to={`/organizations/${orgId}/billing`} className="button secondary">
            Billing
          </Link>
          <Link to={`/organizations/${orgId}`} className="button secondary">
            Back
          </Link>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}

      <div className="panel">
        <h2>Details</h2>
        <form className="inline-form" onSubmit={rename}>
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={255} />
          </label>
          <button type="submit" disabled={isPending("rename")}>
            {isPending("rename") ? "Saving…" : "Save name"}
          </button>
        </form>
        <p className="muted small">The slug is permanent and cannot be changed.</p>
      </div>

      <div className="panel">
        <h2>Members</h2>
        {members.length === 0 ? (
          <p className="muted">No members.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {members.map((member) => {
                const isSelf = member.user_id === user?.id;
                const canManage = viewerIsAdmin && (member.role !== "owner" || viewerIsOwner);
                return (
                  <tr key={member.id}>
                    <td>{member.user_full_name}</td>
                    <td>{member.user_email}</td>
                    <td>
                      {canManage ? (
                        <select
                          aria-label={`Role for ${member.user_full_name}`}
                          value={member.role}
                          onChange={(e) => changeRole(member, e.target.value as MembershipRole)}
                          disabled={isPending(`role:${member.id}`)}
                        >
                          {ROLE_OPTIONS.filter((r) => r !== "owner" || viewerIsOwner).map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className={`badge badge-${member.role === "owner" ? "active" : "draft"}`}>
                          {member.role}
                        </span>
                      )}
                    </td>
                    <td className="actions">
                      {isSelf ? (
                        <button
                          className="link-button danger"
                          onClick={() => removeMember(member)}
                          disabled={isPending(`remove:${member.id}`)}
                        >
                          {isPending(`remove:${member.id}`) ? "Leaving…" : "Leave organization"}
                        </button>
                      ) : canManage ? (
                        <button
                          className="link-button danger"
                          onClick={() => removeMember(member)}
                          disabled={isPending(`remove:${member.id}`)}
                        >
                          {isPending(`remove:${member.id}`) ? "Removing…" : "Remove"}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {viewerIsAdmin && (
          <form className="inline-form" onSubmit={addMember}>
            <input
              type="email"
              placeholder="Member email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              required
            />
            <select
              aria-label="New member role"
              value={newRole}
              onChange={(e) => setNewRole(e.target.value as MembershipRole)}
            >
              {ROLE_OPTIONS.filter((r) => r !== "owner" || viewerIsOwner).map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <button type="submit" disabled={isPending("add")}>
              {isPending("add") ? "Adding…" : "Add member"}
            </button>
          </form>
        )}
      </div>

      {viewerIsAdmin && (
        <div className="panel">
          <h2>AI Provider Keys (BYOK)</h2>
          <p className="muted small">
            Optional per-provider API key for this organization. When set, it replaces the
            platform-shared key for that provider. Keys are never shown again after saving —
            only the last 4 characters.
          </p>
          {credError && <div className="error-box">{credError}</div>}
          {providers.length === 0 ? (
            <p className="muted">No providers available.</p>
          ) : (
            providers.map((provider) => {
              const cred = credentials.find((c) => c.provider_id === provider.provider_id);
              const key = `cred:${provider.provider_id}`;
              return (
                <div key={provider.provider_id} className="inline-form">
                  <strong>{provider.display_name}</strong>
                  {cred ? (
                    <span className="muted small">
                      {cred.masked_key} · updated by {cred.updated_by_email ?? "unknown"} on{" "}
                      {new Date(cred.updated_at).toLocaleDateString()}
                    </span>
                  ) : (
                    <span className="muted small">Using platform-shared key</span>
                  )}
                  <input
                    type="password"
                    placeholder={cred ? "New API key to replace" : "API key"}
                    aria-label={`API key for ${provider.display_name}`}
                    value={keyDrafts[provider.provider_id] ?? ""}
                    onChange={(e) =>
                      setKeyDrafts((prev) => ({
                        ...prev,
                        [provider.provider_id]: e.target.value,
                      }))
                    }
                    disabled={isPending(key)}
                  />
                  <button
                    type="button"
                    onClick={() => saveCredential(provider.provider_id)}
                    disabled={isPending(key) || !(keyDrafts[provider.provider_id] ?? "").trim()}
                  >
                    {isPending(key) ? "Saving…" : cred ? "Replace" : "Set key"}
                  </button>
                  {cred && (
                    <button
                      type="button"
                      className="link-button danger"
                      onClick={() => removeCredential(provider.provider_id)}
                      disabled={isPending(key)}
                    >
                      {isPending(key) ? "Removing…" : "Remove"}
                    </button>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}

      {viewerIsOwner && (
        <div className="panel danger-zone">
          <h2>Danger zone</h2>
          <p className="muted small">
            Deleting this organization permanently removes all of its chatbots, conversations,
            and knowledge. This cannot be undone.
          </p>
          <button className="button danger" onClick={removeOrganization} disabled={isPending("delete")}>
            {isPending("delete") ? "Deleting…" : "Delete organization"}
          </button>
        </div>
      )}
    </section>
  );
}
