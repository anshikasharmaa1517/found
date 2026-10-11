import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useApi } from "../api/context";
import { getRecentReports } from "../api/incidents";
import { listSources, SOURCE_TYPE_LABELS, WITHHELD, type SourceSummary } from "../api/sources";
import { useUser } from "../auth/context";
import { hasRole } from "../auth/user";
import { ErrorNotice } from "../components/ErrorNotice";
import { PenIcon, SearchIcon } from "../components/icons";
import { Empty, PageHeader, SkeletonRows } from "../components/ui";
import { rememberIncident } from "../incident";
import { claimTypeLabel, formatTime } from "../labels";
import { useLoad } from "../useLoad";

/** Status types first, in a fixed order, so cards compare at a glance. */
const TYPE_ORDER = ["MISSING", "FOUND_SAFE", "INJURED", "DECEASED", WITHHELD];

function tone(type: string): string {
  if (type === "FOUND_SAFE") return "ok";
  if (type === "MISSING") return "bad";
  if (type === "INJURED" || type === WITHHELD) return "warn";
  return "";
}

function typeLabel(type: string): string {
  return type === WITHHELD ? "Held for review" : claimTypeLabel(type);
}

function sortedTypes(byType: Record<string, number>): [string, number][] {
  const rank = (t: string) => {
    const i = TYPE_ORDER.indexOf(t);
    return i === -1 ? TYPE_ORDER.length : i;
  };
  return Object.entries(byType).sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
}

/** The source's newest reports, loaded when the card is opened. */
function SourceReports({ incidentId, sourceId }: { incidentId: string; sourceId: string }) {
  const api = useApi();
  const [reports, retry] = useLoad(`source-reports|${incidentId}|${sourceId}`, () =>
    getRecentReports(api, incidentId, 20, sourceId),
  );
  if (reports.status === "loading") return <SkeletonRows label="Loading reports" rows={3} />;
  if (reports.status === "error") return <ErrorNotice error={reports.error} onRetry={retry} />;
  if (reports.data.reports.length === 0) return <p className="meta">No reports yet.</p>;
  return (
    <ol className="source-reports">
      {reports.data.reports.map((r) => {
        const who = r.subject_name ?? "Unknown";
        const to =
          r.subject_type === "PERSON" ? `/people/${encodeURIComponent(r.subject_id)}` : null;
        return (
          <li key={r.claim_id}>
            <div className="row-head">
              {to ? <Link to={to}>{who}</Link> : <strong>{who}</strong>}
              <span className={`pill ${r.withheld ? "warn" : tone(r.claim_type)}`}>
                {r.withheld ? "Sensitive report" : claimTypeLabel(r.claim_type)}
              </span>
            </div>
            <p>{r.withheld ? r.notice : r.excerpt}</p>
            <p className="meta">
              {!r.withheld && r.reported_at && <>Reported {formatTime(r.reported_at)}</>}
              <span className={!r.withheld && r.reported_at ? "meta-sep" : undefined}>
                Received {formatTime(r.ingested_at)}
              </span>
            </p>
          </li>
        );
      })}
    </ol>
  );
}

function SourceCard({ incidentId, source }: { incidentId: string; source: SourceSummary }) {
  const [open, setOpen] = useState(false);
  const panel = `source-${source.id}`;
  return (
    <article className="source-card" aria-labelledby={`${panel}-name`}>
      <header className="source-head">
        <div>
          <h2 id={`${panel}-name`}>{source.name}</h2>
          <p className="meta">{SOURCE_TYPE_LABELS[source.source_type] ?? source.source_type}</p>
        </div>
        <p className="source-count">
          <span className="num">{source.reports}</span>
          <span className="meta">{source.reports === 1 ? " report" : " reports"}</span>
        </p>
      </header>
      {source.reports > 0 && (
        <ul className="pill-row" aria-label="Reports by type">
          {sortedTypes(source.by_type).map(([type, n]) => (
            <li key={type} className={`pill ${tone(type)}`}>
              {typeLabel(type)} <span className="num">{n}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="meta">
        {source.cited_by > 0 ? (
          <>
            Named by {source.cited_by} {source.cited_by === 1 ? "report" : "reports"} from other
            sources. A relay is not independent confirmation.
          </>
        ) : (
          "No other source names this one."
        )}
        {source.latest_at && (
          <span className="meta-sep">Latest received {formatTime(source.latest_at)}</span>
        )}
      </p>
      {source.reports > 0 && (
        <button
          type="button"
          className="link"
          aria-expanded={open}
          aria-controls={panel}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Hide reports" : "Show reports"}
        </button>
      )}
      {open && (
        <div id={panel}>
          <SourceReports incidentId={incidentId} sourceId={source.id} />
        </div>
      )}
    </article>
  );
}

/** Every organization that published in the incident, busiest first. */
export function SourcesPage() {
  const incidentId = useParams().incidentId ?? "";
  const api = useApi();
  const user = useUser();
  const [query, setQuery] = useState("");
  const [sources, retry] = useLoad(`sources|${incidentId}`, () => listSources(api, incidentId));

  useEffect(() => rememberIncident(incidentId), [incidentId]);

  const q = query.trim().toLowerCase();
  const all = sources.status === "ready" ? sources.data.sources : [];
  const shown = all.filter((s) => !q || s.name.toLowerCase().includes(q));

  return (
    <section className="page">
      <PageHeader
        title="Sources"
        description="Reports published by police, hospitals, government and aid groups. Each one keeps its original text and who said it."
        actions={
          hasRole(user, "publisher") ? (
            <Link
              className="button-link primary"
              to={`/incidents/${encodeURIComponent(incidentId)}/report`}
            >
              <PenIcon />
              Publish a report
            </Link>
          ) : undefined
        }
      />
      {sources.status === "loading" && <SkeletonRows label="Loading sources" rows={4} />}
      {sources.status === "error" && (
        <ErrorNotice error={sources.error} notFound="This incident does not exist." onRetry={retry} />
      )}
      {sources.status === "ready" && (
        <>
          <label className="search-field">
            <span>Search sources</span>
            <span className="search-input">
              <SearchIcon />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by organization name"
              />
            </span>
            <span className="meta" aria-live="polite">
              {shown.length} of {all.length} sources shown
            </span>
          </label>
          {all.length === 0 ? (
            <Empty title="No sources yet.">
              Sources appear here as soon as an organization publishes a report.
            </Empty>
          ) : shown.length === 0 ? (
            <Empty
              title="No sources match this search."
              action={
                <button type="button" onClick={() => setQuery("")}>
                  Clear search
                </button>
              }
            />
          ) : (
            <div className="source-grid">
              {shown.map((s) => (
                <SourceCard key={s.id} incidentId={incidentId} source={s} />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
