import { Link } from "react-router-dom";

import { useApi } from "../api/context";
import { getTimeline } from "../api/people";
import { useUser } from "../auth/context";
import { hasRole } from "../auth/user";
import { claimTypeLabel } from "../labels";
import { useLoad } from "../useLoad";
import { ErrorNotice } from "./ErrorNotice";
import { AlertIcon } from "./icons";
import { OpenMatches } from "./MatchCard";
import { WhatChanged } from "./WhatChanged";
import { SkeletonRows } from "./ui";

const PREVIEW_ENTRIES = 20;

/** What is known about one person, beside the list: every report, oldest first, cited. */
export function PersonPreview({
  personId,
  incidentId,
}: {
  personId: string;
  incidentId?: string;
}) {
  const api = useApi();
  const user = useUser();
  const [state, retry] = useLoad(`preview|${personId}`, () =>
    getTimeline(api, personId, { order: "asc", limit: PREVIEW_ENTRIES }),
  );
  if (state.status === "loading") return <SkeletonRows label="Loading the person" rows={4} />;
  if (state.status === "error") return <ErrorNotice error={state.error} onRetry={retry} />;
  const { person, summary, entries, investigations, open_matches, next_cursor } = state.data;
  const full = `/people/${encodeURIComponent(person.id)}`;
  return (
    <section className="preview" aria-labelledby="preview-title" aria-live="polite">
      <h2 id="preview-title">What we know about {person.name}</h2>
      <p className="meta">
        Every report, oldest first, with who said it.
        <span className="meta-sep">
          {person.age === null ? "Age not reported" : `Age ${person.age}`}
        </span>
      </p>
      <div className="preview-summary">
        <strong>{summary.label}</strong>
        <p className="meta">{summary.basis}</p>
      </div>
      <OpenMatches
        person={person}
        matches={open_matches ?? []}
        reviewHref={
          incidentId && hasRole(user, "reviewer", "admin")
            ? `/incidents/${encodeURIComponent(incidentId)}/review?type=identity`
            : undefined
        }
      />
      {summary.conflicts.length > 0 && (
        <div className="disagree" role="note">
          <AlertIcon />
          <div>
            <strong>The reports about {person.name} say different things</strong>
            <p className="meta">
              Other sources say:{" "}
              {summary.conflicts
                .map((c) =>
                  c.withheld
                    ? "a sensitive report"
                    : `${c.source}, ${claimTypeLabel(c.claim_type)}`,
                )
                .join("; ")}
              . Every report is kept; contact the source to confirm.
            </p>
          </div>
        </div>
      )}
      {entries.length === 0 ? (
        <p className="meta">No reports yet.</p>
      ) : (
        <WhatChanged
          entries={entries}
          investigations={investigations}
          incidentId={incidentId}
          citedId={summary.cited_claim_id}
        />
      )}
      <Link className="button-link primary" to={full}>
        {next_cursor ? "Open the full timeline, with more reports" : "Open the full timeline"}
      </Link>
    </section>
  );
}
