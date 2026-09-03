import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

// Deliberately NOT AppLayout: a different trust tier (platform-wide, not
// one organization) with visually distinct chrome so it can never be
// mistaken for a regular organization's admin console.
export default function PlatformAdminLayout() {
  const { user, logout } = useAuth();

  return (
    <div className="layout">
      <aside className="sidebar sidebar-platform">
        <div className="sidebar-brand">PortableAI — Platform Admin</div>
        <nav className="sidebar-nav">
          <NavLink to="/platform-admin" end>
            Organizations
          </NavLink>
          <NavLink to="/platform-admin/settings">Settings</NavLink>
          <NavLink to="/" end>
            ← Back to app
          </NavLink>
        </nav>
        <div className="sidebar-footer">
          {user && <div className="user-chip">{user.full_name}</div>}
          <button className="link-button" onClick={logout}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        <div className="platform-banner">
          Platform-wide view — data spans every organization on the platform.
        </div>
        <Outlet />
      </main>
    </div>
  );
}
