import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";

import { useAuth, useUser } from "../auth/context";
import { displayName, hasRole, initials, mainRole, ROLE_LABELS } from "../auth/user";
import { rememberedIncident } from "../incident";
import type { SocketLike } from "../live/client";
import { useLiveMessage, useLiveStatus } from "../live/context";
import { LiveProvider } from "../live/LiveProvider";
import { Toasts } from "./Toasts";

const STATUS_TEXT = { live: "Live", connecting: "Connecting", offline: "Reconnecting" } as const;

/** Name, email and role, and signing out. Escape or a click outside closes it. */
function AccountMenu({ onSignOut, leaving }: { onSignOut: () => void; leaving: boolean }) {
  const user = useUser();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const role = mainRole(user);
  const name = displayName(user);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onClick(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <div className="menu" ref={box}>
      <button
        type="button"
        className="menu-button"
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={`Account: ${name}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="avatar" aria-hidden="true">
          {initials(name)}
        </span>
        <span className="live-label">{role ? ROLE_LABELS[role] : name}</span>
      </button>
      {open && (
        <div className="menu-panel">
          <div className="who">
            <strong>{name}</strong>
            {user.email && user.email !== name && <span className="meta">{user.email}</span>}
            <div className="meta">
              {user.roles.map((r) => ROLE_LABELS[r]).join(", ")}
              {user.orgId && <span className="meta-sep">{user.orgId}</span>}
            </div>
          </div>
          <button type="button" onClick={onSignOut} disabled={leaving}>
            {leaving ? "Signing out" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}

function Shell({ incidentId }: { incidentId: string | null }) {
  const user = useUser();
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const status = useLiveStatus();
  const [leaving, setLeaving] = useState(false);
  const [unread, setUnread] = useState(0);
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
        <NavLink to="/" className="brand" aria-label="Found, home">
          <span className="brand-mark" aria-hidden="true" />
          Found
        </NavLink>
        {incidentId && (
          <span className="context" title={`Incident ${incidentId}`}>
            <span className="mono">{incidentId}</span>
          </span>
        )}
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
          {incidentId && hasRole(user, "publisher") && (
            <NavLink to={`/incidents/${encodeURIComponent(incidentId)}/upload`}>Upload</NavLink>
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
              <span className="live-label">{STATUS_TEXT[status]}</span>
            </span>
          )}
          <AccountMenu onSignOut={onSignOut} leaving={leaving} />
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
