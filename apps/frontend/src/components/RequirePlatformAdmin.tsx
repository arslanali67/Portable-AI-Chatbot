import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

// Separate trust tier from RequireAuth: a signed-in but non-platform-admin
// user (including an org owner/admin) is redirected to / — the same
// destination an unauthenticated visitor never reaches here at all, since
// hydration failure already sends them to /login upstream.
export function RequirePlatformAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (!user.is_platform_admin) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
