import { useState } from "react";
import { Link } from "react-router-dom";

import type { ApiError } from "../api/client";
import { useApi } from "../api/context";
import { getTimeline, type Timeline } from "../api/people";
import { decideIdentity, type IdentityProposal, type IdentityVerdict } from "../api/review";
import { claimTypeLabel, formatTime, labelFor, MATCH_REASON_LABELS } from "../labels";
import { asApiError } from "../useLoad";

const COMPARE_LIMIT = 20;

type Comparison =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; timelines: Timeline[] }
  | { status: "error" };

function CompareRecord({ timeline }: { timeline: Timeline }) {
  const { person, summary, entries } = timeline;
  return (
    <div className="compare-record">
      <h3>
        <Link to={`/people/${encodeURIComponent(person.id)}`}>{person.name}</Link>
        {person.age !== null && <span className="muted">, {person.age}</span>}
      </h3>
      <p className="muted">{summary.label}</p>
      <ol className="compare-entries">
        {entries.map((entry) =>
          entry.withheld ? (
            <li key={entry.claim_id} className="muted">
              {entry.notice}
            </li>
          ) : (
            <li key={entry.claim_id}>
              <strong>{claimTypeLabel(entry.claim_type)}</strong> from {entry.source},{" "}
              {formatTime(entry.reported_at)}
              <blockquote>{entry.excerpt}</blockquote>
            </li>
          ),
        )}
      </ol>
    </div>
  );
}

/** A proposed pair: why it was proposed, both records side by side, and the decision. */
export function IdentityReview({
  proposal,
  open,
  onDone,
}: {
  proposal: IdentityProposal;
  open: boolean;
  onDone: () => void;
}) {
  const api = useApi();
  const [comparison, setComparison] = useState<Comparison>({ status: "idle" });
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [needsNote, setNeedsNote] = useState(false);

  async function compare() {
    setComparison({ status: "loading" });
    try {
      const timelines = await Promise.all(
        proposal.people.map((p) => getTimeline(api, p.id, { limit: COMPARE_LIMIT })),
      );
      setComparison({ status: "ready", timelines });
    } catch {
      setComparison({ status: "error" });
    }
  }

  async function decide(verdict: IdentityVerdict) {
    if (!note.trim()) {
      setNeedsNote(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await decideIdentity(api, proposal.pair_key, verdict, note);
      onDone();
    } catch (err) {
      setError(asApiError(err));
      setBusy(false);
    }
  }

  const noteId = `identity-note-${proposal.pair_key}`;
  return (
    <div className="identity-review">
      <p>
        {proposal.people.map((p, i) => (
          <span key={p.id}>
            {i > 0 && " and "}
            <Link to={`/people/${encodeURIComponent(p.id)}`}>{p.name}</Link>
            {p.age !== null && `, ${p.age}`}
          </span>
        ))}{" "}
        may be the same person. Records are never merged; your decision links them.
      </p>
      <ul className="reasons" aria-label="Why this pair was proposed">
        {proposal.reasons.map((r) => (
          <li key={r} className="tag">
            {labelFor(MATCH_REASON_LABELS, r)}
          </li>
        ))}
      </ul>

      {comparison.status === "idle" && (
        <button type="button" className="link-button" onClick={compare}>
          Compare their reports
        </button>
      )}
      {comparison.status === "loading" && <p className="muted">Loading both records</p>}
      {comparison.status === "error" && (
        <p className="field-error" role="alert">
          The records could not be loaded.{" "}
          <button type="button" className="link-button" onClick={compare}>
            Try again
          </button>
        </p>
      )}
      {comparison.status === "ready" && (
        <div className="compare">
          {comparison.timelines.map((t) => (
            <CompareRecord key={t.person.id} timeline={t} />
          ))}
        </div>
      )}

      {open && (
        <div className="decision">
          <label htmlFor={noteId}>Note (required)</label>
          <textarea
            id={noteId}
            rows={2}
            maxLength={500}
            value={note}
            aria-invalid={needsNote && !note.trim()}
            onChange={(e) => {
              setNote(e.target.value);
              setNeedsNote(false);
            }}
          />
          {needsNote && !note.trim() && (
            <p className="field-error" role="alert">
              Say what you checked before deciding.
            </p>
          )}
          <div className="actions">
            <button
              type="button"
              className="primary"
              onClick={() => decide("CONFIRMED")}
              disabled={busy}
            >
              Same person
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => decide("REJECTED")}
              disabled={busy}
            >
              Not the same person
            </button>
          </div>
          {error && (
            <p className="field-error" role="alert">
              {error.code === "VERSION_CONFLICT"
                ? "Another reviewer decided this pair meanwhile. Reload to see their decision."
                : "This could not be saved. Try again."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
