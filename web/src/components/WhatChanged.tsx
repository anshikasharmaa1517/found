import { Link } from "react-router-dom";

import type { TimelineEntry, TimelineInvestigation } from "../api/people";
import {
  ATTRIBUTION_LABELS,
  claimTypeLabel,
  formatTime,
  INVESTIGATION_STATUS_LABELS,
  labelFor,
} from "../labels";
import { statusChanges } from "../timeline";

const TONE: Record<string, string> = { MISSING: "bad", FOUND_SAFE: "ok", INJURED: "warn" };

/**
 * The person's history as plain records, as in Trace: each report with its source, type,
 * when it says it happened, when it arrived, and its references. Built from stored fields
 * only; the order is the API's (reported time first).
 */
export function WhatChanged({
  entries,
  newestFirst = false,
  investigations = [],
}: {
  entries: TimelineEntry[];
  newestFirst?: boolean;
  /** Source checks, listed under the report each one checked. */
  investigations?: TimelineInvestigation[];
}) {
  const changes = statusChanges(entries, newestFirst);
  const checksOf = new Map<string, TimelineInvestigation[]>();
  for (const run of investigations) {
    checksOf.set(run.claim_id, [...(checksOf.get(run.claim_id) ?? []), run]);
  }
  const runsShown = entries.reduce(
    (n, e) => n + (e.withheld ? 0 : (checksOf.get(e.claim_id)?.length ?? 0)),
    0,
  );
  const count = entries.length + runsShown;
  return (
    <section className="what-changed" aria-labelledby="what-changed-title">
      <h3 id="what-changed-title">What changed?</h3>
      <p className="what-changed-lead">Summary from stored records</p>
      <p className="meta">
        Ordered by the time each source gave, then by arrival. Reports with no time come last.
        A change compares each report with the one before it.
      </p>
      <p className="meta">
        {count} stored {count === 1 ? "entry" : "entries"}.
      </p>
      <ol className="change-log">
        {entries.map((entry) =>
          entry.withheld ? (
            <li key={entry.claim_id}>
              <div className="change-head">
                <strong>Sensitive report</strong>
              </div>
              <p className="meta">Reported: {formatTime(entry.reported_at)}</p>
              <p>{entry.notice}</p>
            </li>
          ) : (
            <li key={entry.claim_id}>
              <div className="change-head">
                <strong>{entry.source}</strong>
                <span className={`pill ${TONE[entry.claim_type] ?? ""}`}>
                  {claimTypeLabel(entry.claim_type)}
                </span>
                {changes.has(entry.claim_id) && <span className="pill warn">status changed</span>}
              </div>
              <p className="meta">
                Reported: {formatTime(entry.reported_at)}
                {entry.ingested_at && (
                  <span className="meta-sep">Received: {formatTime(entry.ingested_at)}</span>
                )}
              </p>
              <p>{entry.value ?? entry.excerpt}</p>
              <p className="meta change-refs">
                Reference: {entry.external_reference ?? "not given"}
                <span className="meta-sep mono">Claim: {entry.claim_id}</span>
              </p>
              {changes.has(entry.claim_id) && (
                <p className="meta">Previous report: {claimTypeLabel(changes.get(entry.claim_id)!)}</p>
              )}
            </li>
          ),
        ).flatMap((row, i) => {
          const entry = entries[i]!;
          const runs = entry.withheld ? [] : (checksOf.get(entry.claim_id) ?? []);
          return [
            row,
            ...runs.map((run) => (
              <li key={run.id} className="change-check">
                <div className="change-head">
                  <strong>{entry.withheld ? "Sensitive report" : entry.source}</strong>
                  {!entry.withheld && (
                    <span className={`pill ${TONE[entry.claim_type] ?? ""}`}>
                      {claimTypeLabel(entry.claim_type)}
                    </span>
                  )}
                  <span className="pill accent">
                    Investigation · {run.mode} · {run.status}
                  </span>
                </div>
                <p className="meta">
                  Investigation recorded: {formatTime(run.finished_at ?? run.queued_at)}
                </p>
                <p>
                  {run.summary ??
                    (run.attribution
                      ? labelFor(ATTRIBUTION_LABELS, run.attribution)
                      : labelFor(INVESTIGATION_STATUS_LABELS, run.status))}
                </p>
                <p className="meta change-refs">
                  Claim: <span className="mono">{run.claim_id}</span>
                  <span className="meta-sep">
                    Stored investigation:{" "}
                    <Link to={`/investigations/${encodeURIComponent(run.id)}`}>{run.id}</Link>
                  </span>
                </p>
              </li>
            )),
          ];
        })}
      </ol>
    </section>
  );
}
