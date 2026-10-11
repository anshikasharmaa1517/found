import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";

import { useApi } from "../api/context";
import { getIncident, type IncidentInfo } from "../api/incidents";
import { useAuth, useUser } from "../auth/context";
import { displayName, hasRole, initials, mainRole, ROLE_LABELS } from "../auth/user";
import { rememberedIncident } from "../incident";
import type { SocketLike } from "../live/client";
import { useLiveMessage, useLiveStatus } from "../live/context";
import { LiveProvider } from "../live/LiveProvider";
import { useTheme } from "../theme";
import { useLoad } from "../useLoad";
import { ActivityRail } from "./ActivityRail";
import { AlertBanner } from "./AlertBanner";
import { DemoStory } from "./DemoStory";
import {
  BellIcon,
  BuildingIcon,
  GraphIcon,
  MapIcon,
  MoonIcon,
  PenIcon,
  PeopleIcon,
  ReviewIcon,
  SunIcon,
  UploadIcon,
} from "./icons";
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

/** Light or dark; remembered in this browser. */
function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const label = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
  return (
    <button type="button" className="icon-button" onClick={toggle} aria-label={label} title={label}>
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

/** The incident's name and area under the brand; its id while the name loads. */
function CurrentIncident({ incidentId, info }: { incidentId: string; info: IncidentInfo | null }) {
  return (
    <>
      <span className="masthead-rule" aria-hidden="true" />
      <div className="current-incident">
        <span className="eyebrow">Current incident</span>
        <span className="incident-name">
          {info ? info.name : <span className="mono">{incidentId}</span>}
        </span>
        {info?.area && <span className="meta">{info.area}</span>}
      </div>
    </>
  );
}

function Tab({
  to,
  icon,
  active = false,
  label,
  children,
}: {
  to: string;
  icon: ReactNode;
  /** Also current on pages that belong to this tab but live at another address. */
  active?: boolean;
  label?: string;
  children: ReactNode;
}) {
  if (active) {
    return (
      <Link to={to} aria-label={label} className="tab active" aria-current="page">
        {icon}
        {children}
      </Link>
    );
  }
  return (
    <NavLink to={to} end aria-label={label} className={({ isActive }) => (isActive ? "tab active" : "tab")}>
      {icon}
      {children}
    </NavLink>
  );
}

function Shell({ incidentId }: { incidentId: string | null }) {
  const api = useApi();
  const user = useUser();
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const status = useLiveStatus();
  const [incident] = useLoad(`shell-incident|${incidentId ?? ""}`, () =>
    incidentId ? getIncident(api, incidentId) : Promise.resolve(null),
  );
  const info = incident.status === "ready" ? incident.data : null;
  const [leaving, setLeaving] = useState(false);
  const [unread, setUnread] = useState(0);
  const onAlerts = pathname === "/alerts";
  const onHome = pathname === "/";
  const family = hasRole(user, "family");
  const base = incidentId ? `/incidents/${encodeURIComponent(incidentId)}` : null;
  // A person's page and a trace of one report belong with the people in the incident.
  const aboutPeople = pathname.startsWith("/people/") || pathname.startsWith("/investigations/");

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
      <header className="masthead">
        <div className="masthead-id">
          <NavLink to="/" className="brand" aria-label="Found, home">
            <span className="brand-name">Found</span>
            <span className="brand-tag">Every report, with who said it.</span>
          </NavLink>
          {incidentId && <CurrentIncident incidentId={incidentId} info={info} />}
        </div>
        <div className="account">
          {status !== "off" && (
            <span className={`live live-${status}`} title="Live updates">
              <span className="live-label">{STATUS_TEXT[status]}</span>
            </span>
          )}
          <ThemeToggle />
          <AccountMenu onSignOut={onSignOut} leaving={leaving} />
        </div>
      </header>

      {incidentId && info?.is_demo && !onHome && <DemoStory incidentId={incidentId} />}

      <nav className="tabbar" aria-label="Main">
        {base && (
          <>
            <Tab to={`${base}/map`} icon={<MapIcon />}>
              Map
            </Tab>
            <Tab to={`${base}/people`} icon={<PeopleIcon />} active={aboutPeople}>
              People
            </Tab>
            <Tab to={`${base}/sources`} icon={<BuildingIcon />}>
              Sources
            </Tab>
            <Tab to={`${base}/graph`} icon={<GraphIcon />}>
              Graph
            </Tab>
            {hasRole(user, "publisher") && (
              <Tab to={`${base}/report`} icon={<PenIcon />}>
                Report
              </Tab>
            )}
            {hasRole(user, "publisher") && (
              <Tab to={`${base}/upload`} icon={<UploadIcon />}>
                Upload
              </Tab>
            )}
            {hasRole(user, "reviewer", "admin") && (
              <Tab to={`${base}/review`} icon={<ReviewIcon />}>
                Review
              </Tab>
            )}
          </>
        )}
        {family && (
          <Tab
            to="/alerts"
            icon={<BellIcon />}
            label={unread ? `Alerts, ${unread} new` : "Alerts"}
          >
            Alerts{unread > 0 && <span className="count">{unread}</span>}
          </Tab>
        )}
      </nav>

      <AlertBanner />
      <Toasts />
      <div className={incidentId && !onHome ? "workspace with-rail" : "workspace"}>
        <main className="content">
          <Outlet />
        </main>
        {incidentId && !onHome && <ActivityRail incidentId={incidentId} />}
      </div>
      <footer className="site-foot">
        <span>Every report keeps who said it and when. Reports can be wrong: confirm with the source.</span>
      </footer>
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
