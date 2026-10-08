import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth, useUser } from "../auth/context";
import { displayName, mainRole, ROLE_LABELS } from "../auth/user";

export function AppShell() {
  const user = useUser();
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const [leaving, setLeaving] = useState(false);
  const role = mainRole(user);

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
