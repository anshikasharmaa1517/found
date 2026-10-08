import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "./context";
import { hasRole, type Role } from "./user";

/** Renders children for a signed-in user with one of `roles` (any role when omitted). */
export function RequireAuth({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { state } = useAuth();
  const location = useLocation();

  if (state.status === "loading") {
    return (
      <p className="page-status" role="status">
        Loading
      </p>
    );
  }
  if (state.status !== "signedIn") {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  }
  if (state.user.roles.length === 0) {
    return (
      <section className="notice" role="alert">
        <h1>No role assigned</h1>
        <p>Your account does not have a role yet. Ask an admin to add you to a group.</p>
      </section>
    );
  }
  if (roles && !hasRole(state.user, ...roles)) {
    return (
      <section className="notice" role="alert">
        <h1>Not available for your role</h1>
        <p>This page is for {roles.join(" or ")} accounts.</p>
      </section>
    );
  }
  return <>{children}</>;
}
