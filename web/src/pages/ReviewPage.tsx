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
import { Empty, PageHeader, SkeletonRows } from "../components/ui";
import { IdentityReview } from "../components/IdentityReview";
import { IntakeReview } from "../components/IntakeReview";
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
  { type: "intake", label: "Extracted reports" },
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
      <button type="button" className="primary" onClick={submit} disabled={busy}>
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
      {items.map((item) => {
        const decides =
          item.status !== "DONE" && (item.type === "held_alert" || item.type === "conflict");
        return (
          <li
            key={item.id}
            className={`review-item priority-${item.priority}${decides ? " with-decision" : ""}`}
          >
            <div className="review-body">
              <div className="entry-head">
                <strong>{labelFor(TYPE_LABELS, item.type)}</strong>
                <span className={`status-dot${item.priority === 1 ? " warn" : ""}`}>
                  Priority {item.priority}
                </span>
                {item.person && (
                  <Link to={`/people/${encodeURIComponent(item.person.id)}`}>
                    {item.person.name}
                  </Link>
                )}
              </div>
              {item.claim && (
                <>
                  <p className="meta">
                    {claimTypeLabel(item.claim.claim_type)} from {item.claim.source}
                    <span className="meta-sep">{formatTime(item.claim.reported_at)}</span>
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
              {item.intake && (
                <IntakeReview intake={item.intake} incidentId={incidentId} onChange={onChange} />
              )}
              {item.proposal && (
                <IdentityReview
                  proposal={item.proposal}
                  open={item.status === "OPEN"}
                  onDone={onChange}
                />
              )}
              {item.status === "DONE" && (
                <p className="meta">
                  Resolved {formatTime(item.resolved_at)}
                  {item.note && `: ${item.note}`}
                </p>
              )}
            </div>
            {decides && <Decision item={item} incidentId={incidentId} onDone={onChange} />}
          </li>
        );
      })}
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
      <PageHeader
        title="Review queue"
        description="Most urgent first. Every decision is recorded with your name."
      />
      <div className="filters">
        <div className="segmented" role="group" aria-label="Item type">
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
        </div>
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

      {first.status === "loading" && <SkeletonRows label="Loading the queue" rows={4} />}
      {first.status === "error" && (
        <ErrorNotice error={first.error} notFound="This incident was not found." onRetry={retry} />
      )}
      {first.status === "ready" && first.data.items.length === 0 && (
        <Empty title={status === "OPEN" ? "Nothing waits for review." : "Nothing resolved yet."}>
          {status === "OPEN"
            ? "New conflicts, findings, possible duplicates and extracted reports appear here as they arrive."
            : "Items you and other reviewers resolve are listed here with their notes."}
        </Empty>
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
