import { useState } from "react";
import { Link } from "react-router-dom";

import { DELIVERY_LABELS, listAlerts, type Alert } from "../api/alerts";
import { useApi } from "../api/context";
import { ErrorNotice } from "../components/ErrorNotice";
import { Empty, PageHeader, SkeletonRows } from "../components/ui";
import { formatTime } from "../labels";
import { useLiveMessage, useLiveReconnect } from "../live/context";
import { useLoad } from "../useLoad";
import { usePager } from "../usePager";

function AlertItems({ alerts }: { alerts: Alert[] }) {
  return (
    <>
      {alerts.map((alert) => (
        <li key={alert.id} className={alert.severity === "high" ? "alert high" : "alert"}>
          <p>{alert.message}</p>
          <p className="meta">
            {formatTime(alert.created_at)}
            <span className="meta-sep">{DELIVERY_LABELS[alert.delivery_status]}</span>
            <span className="meta-sep">
              <Link to={`/people/${encodeURIComponent(alert.person_id)}`}>View timeline</Link>
            </span>
          </p>
        </li>
      ))}
    </>
  );
}

export function AlertsPage() {
  const api = useApi();
  const [version, setVersion] = useState(0);
  const [first, retry, refresh] = useLoad("alerts", () => listAlerts(api));
  const pager = usePager(
    `alerts|${version}`,
    first.status === "ready" ? first.data.next_cursor : null,
    async (cursor) => {
      const page = await listAlerts(api, cursor);
      return { items: page.alerts, next: page.next_cursor };
    },
  );

  // A notice is only a hint: the feed is fetched again, so it is always the stored truth.
  function reload() {
    refresh();
    setVersion((v) => v + 1);
  }
  useLiveMessage((m) => m.type === "alert.created" && reload());
  useLiveReconnect(reload);

  return (
    <section className="page">
      <PageHeader
        title="Alerts"
        description="Alerts arrive when a new report changes what is known about someone you follow. Earlier reports are always kept on the timeline."
      />
      {first.status === "loading" && <SkeletonRows label="Loading alerts" rows={4} />}
      {first.status === "error" && <ErrorNotice error={first.error} onRetry={retry} />}
      {first.status === "ready" && first.data.alerts.length === 0 && (
        <Empty title="No alerts yet.">
          Follow a person from their page to get alerts when new reports about them arrive.
        </Empty>
      )}
      {first.status === "ready" && first.data.alerts.length > 0 && (
        <ul className="alerts">
          <AlertItems alerts={first.data.alerts} />
          <AlertItems alerts={pager.items} />
        </ul>
      )}
      {pager.error && <ErrorNotice error={pager.error} onRetry={pager.loadMore} />}
      {pager.hasMore && (
        <button type="button" onClick={pager.loadMore} disabled={pager.busy}>
          {pager.busy ? "Loading" : "Load more"}
        </button>
      )}
    </section>
  );
}
