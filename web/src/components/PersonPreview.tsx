import { Link } from "react-router-dom";

import { useApi } from "../api/context";
import { getTimeline } from "../api/people";
import { claimTypeLabel, formatTime } from "../labels";
import { useLoad } from "../useLoad";
import { ErrorNotice } from "./ErrorNotice";
import { SkeletonRows } from "./ui";

const PREVIEW_ENTRIES = 4;

/** What is known about one person, beside the list: the cited status and latest reports. */
export function PersonPreview({ personId }: { personId: string }) {
  const api = useApi();
  const [state, retry] = useLoad(`preview|${personId}`, () =>
    getTimeline(api, personId, { order: "desc", limit: PREVIEW_ENTRIES }),
  );
  if (state.status === "loading") return <SkeletonRows label="Loading the person" rows={4} />;
  if (state.status === "error") return <ErrorNotice error={state.error} onRetry={retry} />;
  const { person, summary, entries } = state.data;
  const full = `/people/${encodeURIComponent(person.id)}`;
  return (
    <section className="preview" aria-labelledby="preview-title" aria-live="polite">
      <p className="eyebrow">What we know</p>
      <h2 id="preview-title">{person.name}</h2>
      <p className="meta">{person.age === null ? "Age not reported" : `Age ${person.age}`}</p>
      <div className="preview-summary">
        <strong>{summary.label}</strong>
        <p className="meta">{summary.basis}</p>
        {summary.conflicts.length > 0 && (
          <p className="meta">
            Other sources say:{" "}
            {summary.conflicts
              .map((c) =>
                c.withheld ? "a sensitive report" : `${c.source}, ${claimTypeLabel(c.claim_type)}`,
              )
              .join("; ")}
          </p>
        )}
      </div>
      <h3>Latest reports</h3>
      <ol className="rail-list">
        {entries.map((e) => (
          <li key={e.claim_id}>
            {e.withheld ? (
              <>
                <strong>Sensitive report</strong>
                <p className="meta">{e.notice}</p>
              </>
            ) : (
              <>
                <strong>{claimTypeLabel(e.claim_type)}</strong>
                <p className="meta">
                  {e.source}
                  <span className="meta-sep">{formatTime(e.reported_at)}</span>
                </p>
                <blockquote>{e.excerpt}</blockquote>
              </>
            )}
          </li>
        ))}
      </ol>
      <Link className="button-link primary" to={full}>
        Open the full timeline
      </Link>
    </section>
  );
}
