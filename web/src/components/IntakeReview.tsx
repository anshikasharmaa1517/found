import { useState } from "react";
import { Link } from "react-router-dom";

import type { ApiError } from "../api/client";
import { useApi } from "../api/context";
import { decideCandidate, type IntakeCandidate, type IntakeJob } from "../api/intake";
import { claimTypeLabel, formatTime } from "../labels";
import { PERSON_CLAIM_TYPES } from "../reportForm";
import { asApiError } from "../useLoad";
import { PersonPicker, type Picked } from "./PersonPicker";

export interface IntakeItem {
  job: IntakeJob;
  extracted_text: string | null;
  candidates: IntakeCandidate[];
}

function Candidate({
  candidate,
  incidentId,
  onDone,
}: {
  candidate: IntakeCandidate;
  incidentId: string;
  onDone: () => void;
}) {
  const api = useApi();
  const person = candidate.subject_type === "PERSON";
  const [claimType, setClaimType] = useState(candidate.claim_type);
  const [attach, setAttach] = useState(false);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function decide(decision: "CONFIRMED" | "REJECTED") {
    setBusy(true);
    setError(null);
    try {
      await decideCandidate(api, candidate.id, {
        decision,
        ...(note.trim() ? { note: note.trim() } : {}),
        ...(decision === "CONFIRMED" && claimType !== candidate.claim_type
          ? { edits: { claim_type: claimType } }
          : {}),
        ...(decision === "CONFIRMED" && attach && picked ? { person_id: picked.id } : {}),
      });
      onDone();
    } catch (err) {
      setError(asApiError(err));
      setBusy(false);
    }
  }

  const id = `cand-${candidate.id}`;
  return (
    <li className="candidate">
      <div className="entry-head">
        <strong>{candidate.subject_name}</strong>
        {candidate.age !== null && <span className="muted">{candidate.age}</span>}
        <span className="tag">{claimTypeLabel(candidate.claim_type)}</span>
        {candidate.status !== "PENDING_REVIEW" && (
          <span className="tag">{candidate.status === "CONFIRMED" ? "Confirmed" : "Rejected"}</span>
        )}
      </div>
      <blockquote>{candidate.span_text}</blockquote>
      <p className="muted">
        Reported time: {candidate.reported_at ? formatTime(candidate.reported_at) : "not given"}
        {candidate.location_name && `. Place: ${candidate.location_name}`}
      </p>
      {candidate.status === "CONFIRMED" && candidate.subject_id && person && (
        <p>
          <Link to={`/people/${encodeURIComponent(candidate.subject_id)}`}>
            Open the person's timeline
          </Link>
        </p>
      )}
      {candidate.status === "PENDING_REVIEW" && (
        <div className="decision">
          {person && (
            <>
              <label htmlFor={`${id}-type`}>Report type</label>
              <select
                id={`${id}-type`}
                value={claimType}
                onChange={(e) => setClaimType(e.target.value)}
              >
                {PERSON_CLAIM_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {claimTypeLabel(t)}
                  </option>
                ))}
              </select>
              <label className="inline">
                <input
                  type="checkbox"
                  checked={attach}
                  onChange={(e) => setAttach(e.target.checked)}
                />
                About someone already listed
              </label>
              {attach && <PersonPicker incidentId={incidentId} picked={picked} onPick={setPicked} />}
            </>
          )}
          <label htmlFor={`${id}-note`}>Note (optional)</label>
          <textarea
            id={`${id}-note`}
            rows={2}
            maxLength={500}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="actions">
            <button
              type="button"
              onClick={() => decide("CONFIRMED")}
              disabled={busy || (attach && !picked)}
            >
              Confirm and publish
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => decide("REJECTED")}
              disabled={busy}
            >
              Reject
            </button>
          </div>
          {error && (
            <p className="field-error" role="alert">
              {error.code === "VERSION_CONFLICT"
                ? "Another reviewer already decided this one."
                : error.status === 422 || error.status === 400
                  ? "This report is not valid as edited. Check the type and person."
                  : "This could not be saved. Try again."}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

/** An uploaded report: the text it was read from and each suggested report to decide. */
export function IntakeReview({
  intake,
  incidentId,
  onChange,
}: {
  intake: IntakeItem;
  incidentId: string;
  onChange: () => void;
}) {
  const [showText, setShowText] = useState(false);
  const { job } = intake;
  return (
    <div className="intake-review">
      <p>
        {job.filename}, received {formatTime(job.created_at)}.{" "}
        {job.dropped_count > 0 &&
          `${job.dropped_count} suggestion${job.dropped_count === 1 ? " was" : "s were"} left out because the text did not support ${job.dropped_count === 1 ? "it" : "them"}. `}
        Each quote below appears in the text; confirm only what the text says.
      </p>
      {intake.extracted_text && (
        <>
          <button type="button" className="link-button" onClick={() => setShowText((v) => !v)}>
            {showText ? "Hide the full text" : "Show the full text"}
          </button>
          {showText && <pre className="extracted-text">{intake.extracted_text}</pre>}
        </>
      )}
      <ol className="candidates">
        {intake.candidates.map((c) => (
          <Candidate key={c.id} candidate={c} incidentId={incidentId} onDone={onChange} />
        ))}
      </ol>
    </div>
  );
}
