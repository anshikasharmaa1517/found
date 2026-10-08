import { Link, useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../api/context";
import { useUser } from "../auth/context";
import { hasRole } from "../auth/user";
import { getTimeline, type Order, type Summary, type TimelineEntry } from "../api/people";
import { ErrorNotice } from "../components/ErrorNotice";
import { rememberedIncident } from "../incident";
import { claimTypeLabel, formatTime, relationLabel } from "../labels";
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
                  {c.source}: {claimTypeLabel(c.claim_type)}
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

function Entries({ entries, citedId }: { entries: TimelineEntry[]; citedId: string | null }) {
  return (
    <>
      {entries.map((entry) => (
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
        </li>
      ))}
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

  const [first, retry] = useLoad(key, () => getTimeline(api, personId, { order }));
  const pager = usePager(key, first.status === "ready" ? first.data.next_cursor : null, async (cursor) => {
    const page = await getTimeline(api, personId, { order, cursor });
    return { items: page.entries, next: page.next_cursor };
  });

  if (first.status === "loading") return <p className="page-status">Loading timeline</p>;
  if (first.status === "error") {
    return (
      <section className="page">
        <ErrorNotice error={first.error} notFound="This person was not found." onRetry={retry} />
      </section>
    );
  }

  const { person, summary, entries } = first.data;
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
          <Entries entries={entries} citedId={summary.cited_claim_id} />
          <Entries entries={pager.items} citedId={summary.cited_claim_id} />
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
