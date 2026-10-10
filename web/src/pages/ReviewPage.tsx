import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import type { ApiError } from "../api/client";
import { useApi } from "../api/context";
import {
  listReviewQueue,
  resolveReviewItem,
  type ReviewItem,
  type ReviewStatus,
  type ReviewType,
} from "../api/review";
import { ErrorNotice } from "../components/ErrorNotice";
import { IdentityReview } from "../components/IdentityReview";
import {
  claimTypeLabel,
  formatTime,
  INVESTIGATION_STATUS_LABELS,
  labelFor,
  REASON_LABELS,
} from "../labels";
import { useLiveMessage, useLiveReconnect } from "../live/context";
import { asApiError, useLoad } from "../useLoad";
import { usePager } from "../usePager";

const TYPE_LABELS: Record<string, string> = {
  held_alert: "Sensitive report held",
  conflict: "Reports disagree",
  finding: "Agent finding",
  identity: "Possible same person",
  intake: "Extracted report",
};

const FILTERS: { type: ReviewType | null; label: string }[] = [
  { type: null, label: "All" },
  { type: "held_alert", label: "Held reports" },
  { type: "conflict", label: "Conflicts" },
  { type: "finding", label: "Findings" },
  { type: "identity", label: "Possible same person" },
];

function Decision({
  item,
  incidentId,
  onDone,
}: {
  item: ReviewItem;
  incidentId: string;
  onDone: () => void;
}) {
  const api = useApi();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const release = item.type === "held_alert";

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await resolveReviewItem(api, incidentId, item.id, note);
      onDone();
    } catch (err) {
      setError(asApiError(err));
      setBusy(false);
    }
  }

  const noteId = `note-${item.id}`;
  return (
    <div className="decision">
      <label htmlFor={noteId}>Note (optional)</label>
      <textarea
        id={noteId}
        rows={2}
        maxLength={500}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      {release && (
        <p className="hint">
          Releasing shows the report in full to everyone and lets held alerts go out. Do it
          after the family has been contacted.
        </p>
      )}
      <button type="button" onClick={submit} disabled={busy}>
        {busy ? "Saving" : release ? "Release report" : "Mark resolved"}
      </button>
      {error && (
        <p className="field-error" role="alert">
          {error.code === "VERSION_CONFLICT"
            ? "Another reviewer already resolved this item."
            : "This could not be saved. Try again."}
        </p>
      )}
    </div>
  );
}

function Items({
  items,
  incidentId,
  onChange,
}: {
  items: ReviewItem[];
  incidentId: string;
  onChange: () => void;
}) {
  return (
    <>
      {items.map((item) => (
        <li key={item.id} className={`review-item priority-${item.priority}`}>
          <div className="entry-head">
            <strong>{labelFor(TYPE_LABELS, item.type)}</strong>
            <span className="tag">Priority {item.priority}</span>
            {item.person && (
              <Link to={`/people/${encodeURIComponent(item.person.id)}`}>{item.person.name}</Link>
            )}
          </div>
          {item.claim && (
            <>
              <p className="muted">
                {claimTypeLabel(item.claim.claim_type)} from {item.claim.source},{" "}
                {formatTime(item.claim.reported_at)}
              </p>
              <blockquote>{item.claim.excerpt}</blockquote>
            </>
          )}
          {item.investigation && (
            <p>
              {labelFor(INVESTIGATION_STATUS_LABELS, item.investigation.status)}.{" "}
              {item.investigation.outcome_reasons
                .map((r) => labelFor(REASON_LABELS, r))
                .join(" ")}{" "}
              <Link to={`/investigations/${encodeURIComponent(item.investigation.id)}`}>
                Open the investigation
              </Link>
            </p>
          )}
          {item.proposal && (
            <IdentityReview
              proposal={item.proposal}
              open={item.status === "OPEN"}
              onDone={onChange}
            />
          )}
          {item.status === "DONE" ? (
            <p className="muted">
              Resolved {formatTime(item.resolved_at)}
              {item.note && `: ${item.note}`}
            </p>
          ) : (
            (item.type === "held_alert" || item.type === "conflict") && (
              <Decision item={item} incidentId={incidentId} onDone={onChange} />
            )
          )}
        </li>
      ))}
    </>
  );
}

export function ReviewPage() {
  const incidentId = useParams().incidentId ?? "";
  const api = useApi();
  const [params, setParams] = useSearchParams();
  const type = (params.get("type") as ReviewType | null) || undefined;
  const status: ReviewStatus = params.get("status") === "DONE" ? "DONE" : "OPEN";
  const key = `${incidentId}|${type ?? ""}|${status}`;
  const [version, setVersion] = useState(0);
  const [first, retry, refresh] = useLoad(key, () =>
    listReviewQueue(api, incidentId, { type, status }),
  );
  const pager = usePager(
    `${key}|${version}`,
    first.status === "ready" ? first.data.next_cursor : null,
    async (cursor) => {
      const page = await listReviewQueue(api, incidentId, { type, status, cursor });
      return { items: page.items, next: page.next_cursor };
    },
  );

  function reload() {
    refresh();
    setVersion((v) => v + 1);
  }
  useLiveMessage((m) => m.type === "review.created" && m.incident_id === incidentId && reload());
  useLiveReconnect(reload);

  function choose(next: { type?: ReviewType | null; status?: ReviewStatus }) {
    const query = new URLSearchParams();
    const t = next.type === undefined ? type : next.type;
    const s = next.status ?? status;
    if (t) query.set("type", t);
    if (s === "DONE") query.set("status", "DONE");
    setParams(query);
  }

  return (
    <section className="page">
      <h1>Review queue</h1>
      <p className="muted">Most urgent first. Every decision is recorded with your name.</p>
      <div className="filters" role="group" aria-label="Item type">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            type="button"
            className={(type ?? null) === f.type ? "chip active" : "chip"}
            aria-pressed={(type ?? null) === f.type}
            onClick={() => choose({ type: f.type })}
          >
            {f.label}
          </button>
        ))}
        <label className="inline">
          Show
          <select
            value={status}
            onChange={(e) => choose({ status: e.target.value as ReviewStatus })}
          >
            <option value="OPEN">Open items</option>
            <option value="DONE">Resolved items</option>
          </select>
        </label>
      </div>

      {first.status === "loading" && <p className="muted">Loading the queue</p>}
      {first.status === "error" && (
        <ErrorNotice error={first.error} notFound="This incident was not found." onRetry={retry} />
      )}
      {first.status === "ready" && first.data.items.length === 0 && (
        <p className="muted">{status === "OPEN" ? "Nothing waits for review." : "Nothing resolved yet."}</p>
      )}
      {first.status === "ready" && first.data.items.length > 0 && (
        <ul className="review-list">
          <Items items={first.data.items} incidentId={incidentId} onChange={reload} />
          <Items items={pager.items} incidentId={incidentId} onChange={reload} />
        </ul>
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
