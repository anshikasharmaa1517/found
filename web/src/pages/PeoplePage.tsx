import { useEffect, useId, useState, type FormEvent, type MouseEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../api/context";
import { getPeopleStats, listPeople, type PersonRow } from "../api/people";
import { listReviewQueue } from "../api/review";
import { useUser } from "../auth/context";
import { hasRole } from "../auth/user";
import { ErrorNotice } from "../components/ErrorNotice";
import { AlertIcon, CheckIcon, PeopleIcon, PersonSearchIcon } from "../components/icons";
import { PersonPreview } from "../components/PersonPreview";
import { PersonStatusDot } from "../components/PersonStatusDot";
import { Empty, PageHeader, SkeletonRows } from "../components/ui";
import { rememberIncident } from "../incident";
import { labelFor, MATCH_REASON_LABELS } from "../labels";
import { useLoad } from "../useLoad";
import { usePager } from "../usePager";

/** On wide screens a name opens the preview beside the list; on phones, the full page. */
function wideScreen(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(min-width: 1024px)").matches;
}

const TONE: Record<string, string> = { MISSING: "bad", FOUND_SAFE: "ok", INJURED: "warn" };

function statusTone(person: PersonRow): string {
  const status = person.status;
  if (!status || status.withheld) return "";
  return TONE[status.claim_type ?? ""] ?? "";
}

/** "Maya Rawat" -> "MR"; a dot or a single name still gives something to show. */
function nameInitials(name: string): string {
  const parts = name.replace(/\./g, " ").split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0]!.charAt(0);
  const last = parts.length > 1 ? parts[parts.length - 1]!.charAt(0) : "";
  return (first + last).toUpperCase();
}

/** One card per person: a status stripe, initials, age, report count and cited status. */
function PersonCards({
  people,
  selected,
  onSelect,
}: {
  people: PersonRow[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  function open(event: MouseEvent<HTMLAnchorElement>, id: string) {
    if (!wideScreen() || event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    onSelect(id);
  }
  return (
    <>
      {people.map((person) => {
        const tone = statusTone(person);
        const reports = person.status?.report_count;
        return (
          <li
            key={person.id}
            className={`person-card ${tone}${person.id === selected ? " selected" : ""}`}
          >
            <span className={`person-initials ${tone}`} aria-hidden="true">
              {nameInitials(person.name)}
            </span>
            <span className="person-main">
              {/* The link covers the whole card; its name stays the person's name. */}
              <Link
                className="card-link"
                to={`/people/${encodeURIComponent(person.id)}`}
                onClick={(e) => open(e, person.id)}
                aria-current={person.id === selected ? "true" : undefined}
              >
                {person.name}
              </Link>
              <span className="meta">
                {person.age === null ? <span className="muted">Not reported</span> : `Age ${person.age}`}
                {reports !== undefined && (
                  <span className="meta-sep">
                    {reports} {reports === 1 ? "report" : "reports"}
                  </span>
                )}
              </span>
            </span>
            <span className="person-status">
              <PersonStatusDot status={person.status} />
              {person.status && person.status.conflicts > 0 && !person.status.withheld && (
                <span className="meta warn-text">Reports differ</span>
              )}
            </span>
          </li>
        );
      })}
    </>
  );
}

/** Four counts across everyone reported. Quietly absent if they cannot be loaded. */
function Stats({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const user = useUser();
  const [stats] = useLoad(`people-stats|${incidentId}`, () => getPeopleStats(api, incidentId));
  if (stats.status !== "ready") return null;
  const s = stats.data;
  const cards = [
    {
      value: s.by_status.MISSING ?? 0,
      label: "Latest report: missing",
      note: "by reported time",
      tone: "bad",
      icon: <PeopleIcon />,
    },
    { value: s.disagree, label: "Sources disagree", note: "all reports kept", tone: "warn", icon: <AlertIcon /> },
    {
      value: s.matches_open,
      label: "Possible matches to review",
      note: "a person decides",
      tone: "accent",
      icon: <PersonSearchIcon />,
    },
    { value: s.matches_decided, label: "Matches decided", note: "by a reviewer", tone: "ok", icon: <CheckIcon /> },
  ];
  return (
    <dl className="stats" aria-label={`${s.people} people reported`}>
      {cards.map((c, i) =>
        // Families see the counts but not the review queue figures, which are staff work.
        i >= 2 && !hasRole(user, "reviewer", "admin") ? null : (
          <div key={c.label} className="stat stat-tile">
            <span className={`stat-icon ${c.tone}`} aria-hidden="true">
              {c.icon}
            </span>
            <dt>{c.label}</dt>
            <dd>
              <span className="stat-value num">{c.value}</span>
              <span className="meta">{c.note}</span>
            </dd>
          </div>
        ),
      )}
    </dl>
  );
}

/** Open identity proposals, for reviewers: two records that may be the same person. */
function PossibleMatches({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const [queue] = useLoad(`matches|${incidentId}`, () =>
    listReviewQueue(api, incidentId, { type: "identity", status: "OPEN" }),
  );
  if (queue.status !== "ready") return null;
  const proposals = queue.data.items.filter((i) => i.proposal).slice(0, 2);
  if (proposals.length === 0) return null;
  return (
    <section className="matches" aria-labelledby="matches-title">
      <h2 id="matches-title">Could these be the same person?</h2>
      <ul className="rail-list">
        {proposals.map((item) => (
          <li key={item.id}>
            <div className="row-head">
              {item.proposal!.people.map((p, i) => (
                <span key={p.id}>
                  {i > 0 && <span className="meta">and </span>}
                  <Link to={`/people/${encodeURIComponent(p.id)}`}>{p.name}</Link>
                  {p.age !== null && <span className="meta">, {p.age}</span>}
                </span>
              ))}
            </div>
            <p className="meta">
              Why: {item.proposal!.reasons.map((r) => labelFor(MATCH_REASON_LABELS, r)).join(", ")}.
              The records stay separate until someone who knows them confirms.
            </p>
          </li>
        ))}
      </ul>
      <Link
        className="button-link"
        to={`/incidents/${encodeURIComponent(incidentId)}/review?type=identity`}
      >
        Review matches
      </Link>
    </section>
  );
}

export function PeoplePage() {
  const incidentId = useParams().incidentId ?? "";
  const api = useApi();
  const user = useUser();
  const [selected, setSelected] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const age = params.get("age") ?? "";
  const resultsId = useId();
  const key = `${incidentId}|${q}|${age}`;

  useEffect(() => rememberIncident(incidentId), [incidentId]);

  const [first, retry] = useLoad(key, () => listPeople(api, incidentId, { q, age }));
  const pager = usePager(key, first.status === "ready" ? first.data.next_cursor : null, async (cursor) => {
    const page = await listPeople(api, incidentId, { q, age, cursor });
    return { items: page.people, next: page.next_cursor };
  });

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    const text = String(form.get("q") ?? "").trim();
    const years = String(form.get("age") ?? "").trim();
    if (text) next.set("q", text);
    if (years) next.set("age", years);
    setParams(next);
  }

  const searching = Boolean(q || age);

  return (
    <section className="page">
      <PageHeader
        title="People"
        description="Everyone reported in this incident. Open a person to see each report and who made it."
      />
      <Stats incidentId={incidentId} />

      <form className="search" role="search" onSubmit={onSearch} key={key}>
        <label>
          Name
          <input name="q" type="search" defaultValue={q} placeholder="For example: Rawat" />
        </label>
        <label className="narrow">
          Age
          <input name="age" type="number" min={0} max={120} defaultValue={age} />
        </label>
        <button type="submit" aria-controls={resultsId}>
          Search
        </button>
      </form>
      {age && <p className="hint">Ages match within 2 years. People with no reported age are included.</p>}

      <div className="people-layout">
      <div id={resultsId} aria-live="polite" className="people-list">
        {hasRole(user, "reviewer", "admin") && <PossibleMatches incidentId={incidentId} />}
        {first.status === "loading" && <SkeletonRows label="Loading people" rows={8} />}
        {first.status === "error" && (
          <ErrorNotice error={first.error} notFound="This incident does not exist." onRetry={retry} />
        )}
        {first.status === "ready" && first.data.people.length === 0 && (
          <Empty
            title={searching ? "No people match this search." : "No people reported yet."}
            action={
              searching ? (
                <button type="button" onClick={() => setParams(new URLSearchParams())}>
                  Clear search
                </button>
              ) : undefined
            }
          >
            {searching
              ? "Try part of a name or leave the age empty. Ages match within 2 years."
              : "People appear here as soon as an organization publishes a report about them."}
          </Empty>
        )}
        {first.status === "ready" && first.data.people.length > 0 && (
          <>
            <ul className="person-cards" aria-label="People">
              <PersonCards people={first.data.people} selected={selected} onSelect={setSelected} />
              <PersonCards people={pager.items} selected={selected} onSelect={setSelected} />
            </ul>
            <div className="table-foot">
              <span>
                Showing {first.data.people.length + pager.items.length}
                {pager.hasMore ? " so far" : ""}
              </span>
              {pager.hasMore && (
                <button type="button" onClick={pager.loadMore} disabled={pager.busy}>
                  {pager.busy ? "Loading" : "Load more"}
                </button>
              )}
            </div>
          </>
        )}
        {pager.error && <ErrorNotice error={pager.error} onRetry={pager.loadMore} />}
      </div>
      <aside className="people-side">
        {selected ? (
          <PersonPreview personId={selected} />
        ) : (
          <div className="empty empty-small">
            <h3>Pick someone to see what is known</h3>
            <p>Their current status, who reported it, and the latest reports appear here.</p>
          </div>
        )}
      </aside>
      </div>
    </section>
  );
}
