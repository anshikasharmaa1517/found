import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../api/context";
import { useUser } from "../auth/context";
import { hasRole } from "../auth/user";
import { getTimeline, type Order, type Summary, type TimelineEntry } from "../api/people";
import { ErrorNotice } from "../components/ErrorNotice";
import { FollowPanel } from "../components/FollowPanel";
import { TraceButton } from "../components/TraceButton";
import { rememberedIncident } from "../incident";
import { claimTypeLabel, formatTime, relationLabel } from "../labels";
import { useLiveMessage, useLiveReconnect } from "../live/context";
import { useLoad } from "../useLoad";
import { usePager } from "../usePager";

function anchor(claimId: string): string {
  return `entry-${claimId}`;
}

function SummaryCard({ summary }: { summary: Summary }) {
  return (
    <section className="summary" aria-labelledby="summary-title">
      <h2 id="summary-title">{summary.label}</h2>
      <p className="muted">
        {summary.basis}
        {summary.cited_claim_id && (
          <>
            {". "}
            <a href={`#${anchor(summary.cited_claim_id)}`}>See the report this is based on</a>
          </>
        )}
      </p>
      {summary.needs_review && (
        <p className="flag" role="note">
          Some reports disagree and are waiting for a reviewer.
        </p>
      )}
      {summary.conflicts.length > 0 && (
        <div>
          <h3>Other sources say</h3>
          <ul>
            {summary.conflicts.map((c) => (
              <li key={c.claim_id}>
                <a href={`#${anchor(c.claim_id)}`}>
                  {c.withheld ? "A sensitive report" : `${c.source}: ${claimTypeLabel(c.claim_type)}`}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="hint">
        Found shows what each source reported and when. It does not decide which report is true.
      </p>
    </section>
  );
}

function Entries({
  entries,
  citedId,
  canTrace,
}: {
  entries: TimelineEntry[];
  citedId: string | null;
  canTrace: boolean;
}) {
  return (
    <>
      {entries.map((entry) =>
        entry.withheld ? (
          <li key={entry.claim_id} id={anchor(entry.claim_id)} className="entry withheld">
            <div className="entry-head">
              <strong>Sensitive report</strong>
              {entry.claim_id === citedId && <span className="tag tag-cited">Used for summary</span>}
            </div>
            <p className="muted">{formatTime(entry.reported_at)}</p>
            <p>{entry.notice}</p>
          </li>
        ) : (
        <li
          key={entry.claim_id}
          id={anchor(entry.claim_id)}
          className={entry.claim_id === citedId ? "entry cited" : "entry"}
        >
          <div className="entry-head">
            <strong>{claimTypeLabel(entry.claim_type)}</strong>
            <span className={`tag tag-${entry.relation.toLowerCase()}`}>
              {relationLabel(entry.relation)}
            </span>
            {entry.claim_id === citedId && <span className="tag tag-cited">Used for summary</span>}
          </div>
          <p className="muted">
            {entry.source}, {formatTime(entry.reported_at)}
          </p>
          {entry.value && <p>{entry.value}</p>}
          <blockquote>{entry.excerpt}</blockquote>
          {canTrace && <TraceButton claimId={entry.claim_id} />}
        </li>
        ),
      )}
    </>
  );
}

export function PersonPage() {
  const personId = useParams().personId ?? "";
  const api = useApi();
  const [params, setParams] = useSearchParams();
  const order: Order = params.get("order") === "desc" ? "desc" : "asc";
  const key = `${personId}|${order}`;
  const incidentId = rememberedIncident();
  const user = useUser();

  const [first, retry, refresh] = useLoad(key, () => getTimeline(api, personId, { order }));
  const [version, setVersion] = useState(0);
  const pager = usePager(`${key}|${version}`, first.status === "ready" ? first.data.next_cursor : null, async (cursor) => {
    const page = await getTimeline(api, personId, { order, cursor });
    return { items: page.entries, next: page.next_cursor };
  });

  // A new report about this person, or a dropped connection, means the page may be behind.
  function reload() {
    refresh();
    setVersion((v) => v + 1);
  }
  useLiveMessage((m) => {
    if ((m.type === "claim.created" || m.type === "alert.created") && m.subject_id === personId) {
      reload();
    }
  });
  useLiveReconnect(reload);

  if (first.status === "loading") return <p className="page-status">Loading timeline</p>;
  if (first.status === "error") {
    return (
      <section className="page">
        <ErrorNotice error={first.error} notFound="This person was not found." onRetry={retry} />
      </section>
    );
  }

  const { person, summary, entries } = first.data;
  const canTrace = hasRole(user, "reviewer", "admin");
  return (
    <section className="page">
      {incidentId && (
        <p>
          <Link to={`/incidents/${encodeURIComponent(incidentId)}/people`}>Back to people</Link>
        </p>
      )}
      <h1>{person.name}</h1>
      <p className="muted">{person.age === null ? "Age not reported" : `Age ${person.age}`}</p>
      {incidentId && hasRole(user, "publisher") && (
        <p>
          <Link
            to={`/incidents/${encodeURIComponent(incidentId)}/report?${new URLSearchParams({
              person: person.id,
              name: person.name,
            })}`}
          >
            Publish a report about this person
          </Link>
        </p>
      )}

      <SummaryCard summary={summary} />

      {hasRole(user, "family") && <FollowPanel personId={person.id} personName={person.name} />}

      <div className="timeline-head">
        <h2>Timeline</h2>
        <label className="inline">
          Order
          <select
            value={order}
            onChange={(e) => setParams(e.target.value === "desc" ? { order: "desc" } : {})}
          >
            <option value="asc">Oldest report first</option>
            <option value="desc">Newest report first</option>
          </select>
        </label>
      </div>
      <p className="hint">Ordered by when each report says it happened, not when it arrived.</p>

      {entries.length === 0 ? (
        <p className="muted">No reports yet.</p>
      ) : (
        <ol className="timeline">
          <Entries entries={entries} citedId={summary.cited_claim_id} canTrace={canTrace} />
          <Entries entries={pager.items} citedId={summary.cited_claim_id} canTrace={canTrace} />
        </ol>
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
