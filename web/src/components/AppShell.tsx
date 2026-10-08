import { useState } from "react";
import { NavLink, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";

import { useAuth, useUser } from "../auth/context";
import { displayName, hasRole, mainRole, ROLE_LABELS } from "../auth/user";
import { rememberedIncident } from "../incident";
import type { SocketLike } from "../live/client";
import { useLiveMessage, useLiveStatus } from "../live/context";
import { LiveProvider } from "../live/LiveProvider";
import { Toasts } from "./Toasts";

const STATUS_TEXT = { live: "Live", connecting: "Connecting", offline: "Reconnecting" } as const;

function Shell({ incidentId }: { incidentId: string | null }) {
  const user = useUser();
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const status = useLiveStatus();
  const [leaving, setLeaving] = useState(false);
  const [unread, setUnread] = useState(0);
  const role = mainRole(user);
  const onAlerts = pathname === "/alerts";
  const family = hasRole(user, "family");

  // Opening the alerts page counts as reading them.
  if (onAlerts && unread !== 0) setUnread(0);
  useLiveMessage((m) => {
    if (m.type === "alert.created" && !onAlerts) setUnread((n) => n + 1);
  });

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
          {incidentId && (
            <NavLink to={`/incidents/${encodeURIComponent(incidentId)}/map`}>Map</NavLink>
          )}
          {incidentId && hasRole(user, "publisher") && (
            <NavLink to={`/incidents/${encodeURIComponent(incidentId)}/report`}>Report</NavLink>
          )}
          {incidentId && hasRole(user, "reviewer", "admin") && (
            <NavLink to={`/incidents/${encodeURIComponent(incidentId)}/review`}>Review</NavLink>
          )}
          {family && (
            <NavLink to="/alerts" aria-label={unread ? `Alerts, ${unread} new` : "Alerts"}>
              Alerts{unread > 0 && <span className="count">{unread}</span>}
            </NavLink>
          )}
        </nav>
        <div className="account">
          {status !== "off" && (
            <span className={`live live-${status}`} title="Live updates">
              {STATUS_TEXT[status]}
            </span>
          )}
          <span className="who">
            {displayName(user)}
            {role && <span className="badge">{ROLE_LABELS[role]}</span>}
          </span>
          <button type="button" className="link" onClick={onSignOut} disabled={leaving}>
            Sign out
          </button>
        </div>
      </header>
      <Toasts />
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}

export function AppShell({
  wsUrl,
  createSocket,
}: {
  wsUrl?: string;
  createSocket?: (url: string) => SocketLike;
}) {
  const user = useUser();
  // The incident in the URL wins; elsewhere, the one opened last.
  const inUrl = useMatch("/incidents/:incidentId/*")?.params.incidentId;
  const incidentId = inUrl ?? rememberedIncident();
  // Staff follow the incident's feed; family accounts only get their own alerts.
  const staff = hasRole(user, "publisher", "reviewer", "admin");

  return (
    <LiveProvider wsUrl={wsUrl} createSocket={createSocket} incidentId={staff ? incidentId : null}>
      <Shell incidentId={incidentId} />
    </LiveProvider>
  );
}
