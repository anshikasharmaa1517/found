import { useState } from "react";
import { Link } from "react-router-dom";

import { DELIVERY_LABELS, listAlerts, type Alert } from "../api/alerts";
import { useApi } from "../api/context";
import { ErrorNotice } from "../components/ErrorNotice";
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
          <p className="muted">
            {formatTime(alert.created_at)}. {DELIVERY_LABELS[alert.delivery_status]}.
          </p>
          <Link to={`/people/${encodeURIComponent(alert.person_id)}`}>View timeline</Link>
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
      <h1>Alerts</h1>
      <p className="muted">
        Alerts arrive when a new report changes what is known about someone you follow. Earlier
        reports are always kept on the timeline.
      </p>
      {first.status === "loading" && <p className="muted">Loading alerts</p>}
      {first.status === "error" && <ErrorNotice error={first.error} onRetry={retry} />}
      {first.status === "ready" && first.data.alerts.length === 0 && (
        <p className="muted">No alerts yet. Follow a person from their page to get alerts.</p>
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
