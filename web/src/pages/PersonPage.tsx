import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../api/context";
import { useUser } from "../auth/context";
import { hasRole } from "../auth/user";
import {
  getTimeline,
  type IdentityLink,
  type Order,
  type Summary,
  type TimelineEntry,
  type TimelineInvestigation,
  type VisibleEntry,
} from "../api/people";
import { ErrorNotice } from "../components/ErrorNotice";
import { FollowPanel } from "../components/FollowPanel";
import { WhatChanged } from "../components/WhatChanged";
import { TraceButton } from "../components/TraceButton";
import { PageHeader, SkeletonRows } from "../components/ui";
import { rememberedIncident } from "../incident";
import {
  ATTRIBUTION_LABELS,
  claimTypeLabel,
  formatTime,
  IDENTITY_DECISION_LABELS,
  INVESTIGATION_STATUS_LABELS,
  labelFor,
} from "../labels";
import { useLiveMessage, useLiveReconnect } from "../live/context";
import { entryAnchor } from "../timeline";
import { useLoad } from "../useLoad";
import { usePager } from "../usePager";

/** Reviewers' decisions about other records of this person. Nothing is merged. */
function IdentityLinks({ links }: { links: IdentityLink[] }) {
  if (links.length === 0) return null;
  return (
    <section aria-labelledby="identity-title">
      <h2 id="identity-title">Other records</h2>
      <ul className="identity-links">
        {links.map((link) => (
          <li key={link.pair_key}>
            {labelFor(IDENTITY_DECISION_LABELS, link.decision)}{" "}
            <Link to={`/people/${encodeURIComponent(link.other_person_id)}`}>another record</Link>{" "}
            <span className="muted">by a reviewer, {formatTime(link.decided_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
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
            <a href={`#${entryAnchor(summary.cited_claim_id)}`}>See the report this is based on</a>
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
                <a href={`#${entryAnchor(c.claim_id)}`}>
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

/**
 * Where each report came from, as in Trace: the source checks already run, and for
 * reviewers a way to start one. The model only labels; code decides, and a person
 * makes the final call.
 */
function SourceChecks({
  entries,
  investigations,
  canTrace,
}: {
  entries: TimelineEntry[];
  investigations: TimelineInvestigation[];
  canTrace: boolean;
}) {
  const visible = entries.filter((e): e is VisibleEntry => !e.withheld);
  return (
    <section className="source-checks" aria-labelledby="source-checks-title">
      <h2 id="source-checks-title">Where did this report come from?</h2>
      <p className="meta">
        A source check asks who a report is quoting, then compares it with that source&apos;s own
        reports when it can. A person makes the final call, and a relay is never treated as
        independent confirmation.
      </p>
      {canTrace ? (
        <ul className="check-list">
          {visible.map((entry) => {
            const runs = investigations.filter((i) => i.claim_id === entry.claim_id);
            const latest = runs[runs.length - 1];
            return (
              <li key={entry.claim_id}>
                <div className="change-head">
                  <strong>{entry.source}</strong>
                  <span className="meta">{claimTypeLabel(entry.claim_type)}</span>
                </div>
                <p className="meta">{entry.excerpt}</p>
                {latest ? (
                  <div className="check-result" role="status">
                    <p className="change-head">
                      <span className={`pill ${latest.mode === "LIVE" ? "ok" : ""}`}>{latest.mode}</span>
                      <strong>{labelFor(INVESTIGATION_STATUS_LABELS, latest.status)}</strong>
                    </p>
                    <p>
                      {latest.summary ??
                        (latest.attribution
                          ? labelFor(ATTRIBUTION_LABELS, latest.attribution)
                          : "No finding recorded yet.")}
                    </p>
                    <p className="meta">
                      Recorded run: {formatTime(latest.finished_at ?? latest.queued_at)}
                      <span className="meta-sep">
                        <Link to={`/investigations/${encodeURIComponent(latest.id)}`}>
                          See the source check
                        </Link>
                      </span>
                    </p>
                  </div>
                ) : (
                  <>
                    <p className="meta">No check recorded yet for this report.</p>
                    <TraceButton claimId={entry.claim_id} />
                  </>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="meta">
          Reviewers check where reports came from. Their findings appear here once a reviewer
          has accepted them.
        </p>
      )}
    </section>
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

  if (first.status === "loading") {
    return (
      <section className="page">
        <div className="skeleton-title skeleton-bar" aria-hidden="true" />
        <SkeletonRows label="Loading timeline" rows={4} />
      </section>
    );
  }
  if (first.status === "error") {
    return (
      <section className="page">
        <ErrorNotice error={first.error} notFound="This person was not found." onRetry={retry} />
      </section>
    );
  }

  const { person, summary, identity, entries } = first.data;
  const investigations = first.data.investigations ?? [];
  const canTrace = hasRole(user, "reviewer", "admin");
  return (
    <section className="page">
      {incidentId && (
        <p className="crumb">
          <Link to={`/incidents/${encodeURIComponent(incidentId)}/people`}>Back to people</Link>
        </p>
      )}
      <PageHeader
        title={person.name}
        description={person.age === null ? "Age not reported" : `Age ${person.age}`}
        actions={
          incidentId &&
          hasRole(user, "publisher") && (
            <Link
              className="button-link primary"
              to={`/incidents/${encodeURIComponent(incidentId)}/report?${new URLSearchParams({
                person: person.id,
                name: person.name,
              })}`}
            >
              Publish a report about this person
            </Link>
          )
        }
      />

      <div className="split">
        <div className="split-main">
      <SummaryCard summary={summary} />

      <div className="timeline-head">
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

      {entries.length === 0 ? (
        <p className="empty">No reports yet.</p>
      ) : (
        <WhatChanged
          entries={[...entries, ...pager.items]}
          newestFirst={order === "desc"}
          investigations={investigations}
          incidentId={incidentId}
          citedId={summary.cited_claim_id}
          showRelation
        />
      )}
      {pager.error && <ErrorNotice error={pager.error} onRetry={pager.loadMore} />}
      {pager.hasMore && (
        <button type="button" onClick={pager.loadMore} disabled={pager.busy}>
          {pager.busy ? "Loading" : "Load more"}
        </button>
      )}
      {entries.length > 0 && (
        <SourceChecks
          entries={[...entries, ...pager.items]}
          investigations={investigations}
          canTrace={canTrace}
        />
      )}
        </div>
        <aside className="split-side">
          {hasRole(user, "family") && <FollowPanel personId={person.id} personName={person.name} />}
          <IdentityLinks links={identity} />
        </aside>
      </div>
    </section>
  );
}
