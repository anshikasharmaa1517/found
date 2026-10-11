import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { TimelineEntry, VisibleEntry } from "../api/people";
import { SOURCE_TYPE_LABELS } from "../api/sources";
import { claimTypeLabel, formatTime, relationLabel, reportSentence } from "../labels";
import { entryAnchor, statusChanges } from "../timeline";
import { ClockIcon } from "./icons";

const TONE: Record<string, string> = {
  MISSING: "bad",
  FOUND_SAFE: "ok",
  INJURED: "warn",
  SHELTERED: "ok",
};

/**
 * Every report as a card on a line, as in Trace: what it says, when, who said it, and what
 * changed since the report before. Nothing here decides which report is true.
 */
export function ReportTimeline({
  entries,
  newestFirst = false,
  incidentId,
  citedId = null,
  showRelation = false,
  actions,
}: {
  entries: TimelineEntry[];
  newestFirst?: boolean;
  /** Links a report's place to the incident map, when known. */
  incidentId?: string | null;
  citedId?: string | null;
  showRelation?: boolean;
  /** Extra controls under a visible report, for example starting a trace. */
  actions?: (entry: VisibleEntry) => ReactNode;
}) {
  const changes = statusChanges(entries, newestFirst);
  return (
    <ol className="report-cards">
      {entries.map((entry) => {
        if (entry.withheld) {
          return (
            <li key={entry.claim_id} id={entryAnchor(entry.claim_id)} className="report-card withheld">
              <span className="report-dot" aria-hidden="true" />
              <div className="report-body">
                <div className="report-head">
                  <strong>Sensitive report</strong>
                  <span className="report-time">
                    <ClockIcon size={14} />
                    {formatTime(entry.reported_at)}
                  </span>
                </div>
                <p>{entry.notice}</p>
                {entry.claim_id === citedId && <span className="tag tag-cited">Used for summary</span>}
              </div>
            </li>
          );
        }
        const tone = TONE[entry.claim_type] ?? "";
        const before = changes.get(entry.claim_id);
        const kind = entry.source_type ? SOURCE_TYPE_LABELS[entry.source_type] : null;
        return (
          <li
            key={entry.claim_id}
            id={entryAnchor(entry.claim_id)}
            className={`report-card ${tone}${entry.claim_id === citedId ? " cited" : ""}`}
          >
            <span className="report-dot" aria-hidden="true" />
            <div className="report-body">
              <div className="report-head">
                <strong className="report-sentence">{reportSentence(entry.claim_type)}</strong>
                <span className="report-time">
                  <ClockIcon size={14} />
                  {formatTime(entry.reported_at)}
                </span>
              </div>
              {(before || showRelation || entry.claim_id === citedId) && (
                <div className="report-tags">
                  {before && (
                    <span className="pill warn">Changed from {claimTypeLabel(before)}</span>
                  )}
                  {showRelation && (
                    <span className={`tag tag-${entry.relation.toLowerCase()}`}>
                      {relationLabel(entry.relation)}
                    </span>
                  )}
                  {entry.claim_id === citedId && <span className="tag tag-cited">Used for summary</span>}
                </div>
              )}
              {entry.value && <p className="report-value">{entry.value}</p>}
              <p>{entry.excerpt}</p>
              <p className="meta">
                From <strong className="report-source">{entry.source}</strong>
                {kind && ` (${kind})`}
              </p>
              {(entry.ingested_at || entry.external_reference) && (
                <p className="meta report-facts">
                  {entry.ingested_at && <>Received {formatTime(entry.ingested_at)}</>}
                  {entry.external_reference && (
                    <span className={entry.ingested_at ? "meta-sep" : undefined}>
                      Reference {entry.external_reference}
                    </span>
                  )}
                </p>
              )}
              {entry.location && incidentId && (
                <Link
                  className="report-place"
                  to={`/incidents/${encodeURIComponent(incidentId)}/map?${new URLSearchParams({
                    place: entry.location.id,
                  })}`}
                >
                  Show {entry.location.name} on the map
                </Link>
              )}
              {actions?.(entry)}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
