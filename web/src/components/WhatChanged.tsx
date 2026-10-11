import type { TimelineEntry } from "../api/people";
import { claimTypeLabel, formatTime } from "../labels";
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
}: {
  entries: TimelineEntry[];
  newestFirst?: boolean;
}) {
  const changes = statusChanges(entries, newestFirst);
  return (
    <section className="what-changed" aria-labelledby="what-changed-title">
      <h3 id="what-changed-title">What changed?</h3>
      <p className="what-changed-lead">Summary from stored records</p>
      <p className="meta">
        Ordered by the time each source gave, then by arrival. Reports with no time come last.
        A change compares each report with the one before it.
      </p>
      <p className="meta">
        {entries.length} stored {entries.length === 1 ? "entry" : "entries"}.
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
        )}
      </ol>
    </section>
  );
}
