import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

export default function AppLayout() {
  const { user, logout } = useAuth();

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-brand">PortableAI</div>
        <nav className="sidebar-nav">
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/organizations" end>
            Organizations
          </NavLink>
          <NavLink to="/providers">AI Providers</NavLink>
          {user?.is_platform_admin && (
            <NavLink to="/platform-admin">Platform Admin</NavLink>
          )}
        </nav>
        <div className="sidebar-footer">
          {user && <div className="user-chip">{user.full_name}</div>}
          <button className="link-button" onClick={logout}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}