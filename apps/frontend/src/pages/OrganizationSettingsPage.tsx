import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage, useAuth } from "../auth/AuthContext";
import type { Membership, MembershipRole, Organization } from "../api/types";

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
        <Link to={`/organizations/${orgId}`} className="button secondary">
          Back
        </Link>
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
