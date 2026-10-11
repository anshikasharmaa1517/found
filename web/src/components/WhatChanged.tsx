import { Link } from "react-router-dom";

import type { TimelineEntry, TimelineInvestigation, VisibleEntry } from "../api/people";
import { SOURCE_TYPE_LABELS } from "../api/sources";
import {
  ATTRIBUTION_LABELS,
  claimTypeLabel,
  formatTime,
  INVESTIGATION_STATUS_LABELS,
  labelFor,
  relationLabel,
} from "../labels";
import { entryAnchor, statusChanges } from "../timeline";

const TONE: Record<string, string> = { MISSING: "bad", FOUND_SAFE: "ok", INJURED: "warn" };

function reportedTime(iso: string | null): string {
  return iso ? formatTime(iso) : "time unknown";
}

/** A source check, under the report it checked. */
function CheckRow({ run, entry }: { run: TimelineInvestigation; entry: VisibleEntry }) {
  return (
    <li className="change-check">
      <div className="change-head">
        <strong>{entry.source}</strong>
        <span className={`pill ${TONE[entry.claim_type] ?? ""}`}>
          {claimTypeLabel(entry.claim_type)}
        </span>
        <span className="pill accent">
          Investigation · {run.mode} · {run.status}
        </span>
      </div>
      <p className="meta">Investigation recorded: {formatTime(run.finished_at ?? run.queued_at)}</p>
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
  );
}

/**
 * Every report about a person as plain records, as in Trace's "What changed?": who said
 * it, what kind of source it is, when it says it happened and when it arrived, its
 * references, and whether it changed the status from the report before. Source checks
 * sit under the report they checked. Built from stored fields only.
 */
export function WhatChanged({
  entries,
  newestFirst = false,
  investigations = [],
  incidentId,
  citedId = null,
  showRelation = false,
}: {
  entries: TimelineEntry[];
  newestFirst?: boolean;
  investigations?: TimelineInvestigation[];
  /** Links a report's place to the incident map, when known. */
  incidentId?: string | null;
  /** The report the summary is based on. */
  citedId?: string | null;
  showRelation?: boolean;
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
      <h2 id="what-changed-title">What changed?</h2>
      <p className="meta">
        Every report, {newestFirst ? "newest" : "oldest"} first, from stored records. Ordered by
        the time each source gave, then by arrival; reports with no time come last. A change
        compares each report with the one before it.
      </p>
      <p className="meta">
        {count} stored {count === 1 ? "entry" : "entries"}.
      </p>
      <ol className="change-log">
        {entries.flatMap((entry) => {
          const cited = entry.claim_id === citedId;
          if (entry.withheld) {
            return [
              <li
                key={entry.claim_id}
                id={entryAnchor(entry.claim_id)}
                className={cited ? "cited" : undefined}
              >
                <div className="change-head">
                  <strong>Sensitive report</strong>
                  {cited && <span className="tag tag-cited">Used for summary</span>}
                </div>
                <p className="meta">Reported: {reportedTime(entry.reported_at)}</p>
                <p>{entry.notice}</p>
              </li>,
            ];
          }
          const before = changes.get(entry.claim_id);
          const kind = entry.source_type ? SOURCE_TYPE_LABELS[entry.source_type] : null;
          return [
            <li
              key={entry.claim_id}
              id={entryAnchor(entry.claim_id)}
              className={cited ? "cited" : undefined}
            >
              <div className="change-head">
                <strong>{entry.source}</strong>
                {kind && <span className="meta">({kind})</span>}
                <span className={`pill ${TONE[entry.claim_type] ?? ""}`}>
                  {claimTypeLabel(entry.claim_type)}
                </span>
                {before && <span className="pill warn">status changed</span>}
                {showRelation && (
                  <span className={`tag tag-${entry.relation.toLowerCase()}`}>
                    {relationLabel(entry.relation)}
                  </span>
                )}
                {cited && <span className="tag tag-cited">Used for summary</span>}
              </div>
              <p className="meta">
                Reported: {reportedTime(entry.reported_at)}
                {entry.ingested_at && (
                  <span className="meta-sep">Received: {formatTime(entry.ingested_at)}</span>
                )}
              </p>
              {entry.value && <p className="change-value">{entry.value}</p>}
              <p>{entry.excerpt}</p>
              <p className="meta change-refs">
                Reference: {entry.external_reference ?? "not given"}
                <span className="meta-sep mono">Claim: {entry.claim_id}</span>
              </p>
              {before && <p className="meta">Previous report: {claimTypeLabel(before)}</p>}
              {entry.location && incidentId && (
                <Link
                  className="change-place"
                  to={`/incidents/${encodeURIComponent(incidentId)}/map?${new URLSearchParams({
                    place: entry.location.id,
                  })}`}
                >
                  Show {entry.location.name} on the map
                </Link>
              )}
            </li>,
            ...(checksOf.get(entry.claim_id) ?? []).map((run) => (
              <CheckRow key={run.id} run={run} entry={entry} />
            )),
          ];
        })}
      </ol>
    </section>
  );
}
