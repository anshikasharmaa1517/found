import { useState } from "react";
import { NavLink, Outlet, useMatch, useNavigate } from "react-router-dom";

import { useAuth, useUser } from "../auth/context";
import { displayName, hasRole, mainRole, ROLE_LABELS } from "../auth/user";
import { rememberedIncident } from "../incident";

export function AppShell() {
  const user = useUser();
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const [leaving, setLeaving] = useState(false);
  const role = mainRole(user);
  // The incident in the URL wins; elsewhere, the one opened last.
  const inUrl = useMatch("/incidents/:incidentId/*")?.params.incidentId;
  const incidentId = inUrl ?? rememberedIncident();

  async function onSignOut() {
    setLeaving(true);
    try {
      await signOut();
    } finally {
      navigate("/sign-in", { replace: true });
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          Found
        </NavLink>
        <nav aria-label="Main">
          <NavLink to="/" end>
            Home
          </NavLink>
          {incidentId && (
            <NavLink to={`/incidents/${encodeURIComponent(incidentId)}/people`}>People</NavLink>
          )}
          {incidentId && hasRole(user, "publisher") && (
            <NavLink to={`/incidents/${encodeURIComponent(incidentId)}/report`}>Report</NavLink>
          )}
        </nav>
        <div className="account">
          <span className="who">
            {displayName(user)}
            {role && <span className="badge">{ROLE_LABELS[role]}</span>}
          </span>
          <button type="button" className="link" onClick={onSignOut} disabled={leaving}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
