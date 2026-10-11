import { useState } from "react";
import { Link } from "react-router-dom";

import { listAlerts } from "../api/alerts";
import { useApi } from "../api/context";
import { getRecentReports, type RecentReport } from "../api/incidents";
import { useUser } from "../auth/context";
import { hasRole } from "../auth/user";
import { claimTypeLabel, formatTime } from "../labels";
import { useLiveMessage, useLiveReconnect } from "../live/context";
import { useLoad } from "../useLoad";
import { SkeletonRows } from "./ui";

const LIVE_MAX = 6;

interface LiveNotice {
  id: string;
  text: string;
  to: string;
  at: string;
}

/** Families: their own alerts. Staff: what arrived over the live feed this session. */
function Notifications({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const user = useUser();
  const family = hasRole(user, "family");
  const reviews = hasRole(user, "reviewer", "admin");
  const [version, setVersion] = useState(0);
  const [alerts] = useLoad(`rail-alerts|${version}`, () =>
    family ? listAlerts(api) : Promise.resolve(null),
  );
  const [live, setLive] = useState<LiveNotice[]>([]);

  useLiveMessage((m) => {
    if (m.type === "alert.created" && family) setVersion((v) => v + 1);
    let notice: LiveNotice | null = null;
    if (m.type === "claim.created" && m.incident_id === incidentId) {
      notice = {
        id: m.claim_id,
        text: "A new report arrived.",
        to: `/people/${encodeURIComponent(m.subject_id)}`,
        at: m.at,
      };
    } else if (m.type === "review.created" && reviews && m.incident_id === incidentId) {
      notice = {
        id: m.review_id,
        text: "A new item is waiting for review.",
        to: `/incidents/${encodeURIComponent(incidentId)}/review`,
        at: new Date().toISOString(),
      };
    }
    if (notice) {
      const next = notice;
      setLive((list) => [next, ...list.filter((n) => n.id !== next.id)].slice(0, LIVE_MAX));
    }
  });

  const items: LiveNotice[] =
    family && alerts.status === "ready" && alerts.data
      ? alerts.data.alerts.slice(0, LIVE_MAX).map((a) => ({
          id: a.id,
          text: a.message,
          to: `/people/${encodeURIComponent(a.person_id)}`,
          at: a.created_at,
        }))
      : live;

  return (
    <section className="rail-section" aria-labelledby="notifications-title">
      <h2 id="notifications-title">Notifications</h2>
      <p className="meta">
        {family
          ? "Alerts about the people you follow."
          : "New reports and review items, as they arrive."}
      </p>
      {family && alerts.status === "loading" && <SkeletonRows label="Loading alerts" rows={2} />}
      {items.length === 0 && !(family && alerts.status === "loading") ? (
        <div className="empty empty-small">
          <h3>No notifications yet</h3>
          <p>
            {family
              ? "Follow a person from their page to hear when a new report about them arrives."
              : "When a new report comes in, it appears here without reloading."}
          </p>
        </div>
      ) : (
        <ul className="rail-list">
          {items.map((n) => (
            <li key={n.id}>
              <Link to={n.to}>{n.text}</Link>
              <span className="meta">{formatTime(n.at)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RecentItem({ report }: { report: RecentReport }) {
  const who = report.subject_name ?? "Unknown";
  const to =
    report.subject_type === "PERSON" ? `/people/${encodeURIComponent(report.subject_id)}` : null;
  return (
    <li>
      <div className="row-head">
        {to ? <Link to={to}>{who}</Link> : <strong>{who}</strong>}
        <span className="meta">
          {report.withheld ? "Sensitive report" : claimTypeLabel(report.claim_type)}
        </span>
      </div>
      <p className="meta">
        {report.withheld ? report.notice : report.source}
        <span className="meta-sep">{formatTime(report.ingested_at)}</span>
      </p>
    </li>
  );
}

/** The newest reports in the incident, refreshed when a new one arrives. */
function RecentUpdates({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const [version, setVersion] = useState(0);
  const [recent, retry] = useLoad(`recent|${incidentId}|${version}`, () =>
    getRecentReports(api, incidentId),
  );
  useLiveMessage((m) => {
    if (m.type === "claim.created" && m.incident_id === incidentId) setVersion((v) => v + 1);
  });
  useLiveReconnect(() => setVersion((v) => v + 1));

  return (
    <section className="rail-section" aria-labelledby="recent-title">
      <div className="rail-head">
        <h2 id="recent-title">Recent updates</h2>
        <span className="meta">Newest first</span>
      </div>
      {recent.status === "loading" && <SkeletonRows label="Loading recent updates" rows={4} />}
      {recent.status === "error" && (
        // The rail is secondary, so a failure here is a quiet note, not an alert.
        <p className="meta">
          Recent updates could not load.{" "}
          <button type="button" className="link" onClick={retry}>
            Try again
          </button>
        </p>
      )}
      {recent.status === "ready" &&
        (recent.data.reports.length === 0 ? (
          <p className="meta">No reports yet.</p>
        ) : (
          <ul className="rail-list">
            {recent.data.reports.map((r) => (
              <RecentItem key={r.claim_id} report={r} />
            ))}
          </ul>
        ))}
    </section>
  );
}

export function ActivityRail({ incidentId }: { incidentId: string }) {
  return (
    <aside className="rail" aria-label="Notifications and recent updates">
      <Notifications incidentId={incidentId} />
      <RecentUpdates incidentId={incidentId} />
    </aside>
  );
}
