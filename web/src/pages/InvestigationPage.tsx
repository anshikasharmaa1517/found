import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../api/context";
import { reviewFinding } from "../api/review";
import {
  getInvestigation,
  RUNNING_STATUSES,
  type Investigation,
  type Step,
} from "../api/investigations";
import { ErrorNotice } from "../components/ErrorNotice";
import { PageHeader, SkeletonRows } from "../components/ui";
import {
  ATTRIBUTION_LABELS,
  COMPARISON_LABELS,
  FAILURE_LABELS,
  formatTime,
  INVESTIGATION_STATUS_LABELS,
  labelFor,
  MODE_LABELS,
  REASON_LABELS,
} from "../labels";
import { useLiveMessage, useLiveReconnect } from "../live/context";
import { asApiError, useLoad } from "../useLoad";

const STATUS_TONE: Record<string, string> = {
  QUEUED: "accent pulse",
  RUNNING: "accent pulse",
  COMPLETED: "ok",
  NEEDS_REVIEW: "warn",
  FAILED: "bad",
};

const KIND_LABELS: Record<string, string> = {
  MODEL: "Model",
  TOOL: "Tool",
  GUARD: "Limit",
  ERROR: "Error",
};

function seconds(ms: number | null): string {
  return ms === null ? "" : `${(ms / 1000).toFixed(1)} s`;
}

function Finding({ investigation }: { investigation: Investigation }) {
  const { finding, outcome_reasons: reasons } = investigation;
  if (!finding) return null;
  return (
    <section className="finding" aria-labelledby="finding-title">
      <h2 id="finding-title">Finding</h2>
      <dl className="facts">
        <dt>Attribution</dt>
        <dd>{labelFor(ATTRIBUTION_LABELS, finding.attribution)}</dd>
        <dt>Named source</dt>
        <dd>{finding.referenced_source?.name ?? finding.referenced_source?.id ?? "None"}</dd>
        <dt>Comparison</dt>
        <dd>{labelFor(COMPARISON_LABELS, finding.comparison)}</dd>
      </dl>
      <p>{finding.summary}</p>
      <h3>Cited text</h3>
      <ul className="citations">
        {finding.citations.map((c) => (
          <li key={`${c.claim_id}|${c.excerpt}`}>
            <blockquote>{c.excerpt}</blockquote>
            <p className="meta mono">Report {c.claim_id}</p>
          </li>
        ))}
      </ul>
      {reasons.length > 0 && (
        <div className="flag" role="note">
          <p>Sent to a reviewer:</p>
          <ul>
            {reasons.map((r) => (
              <li key={r}>{labelFor(REASON_LABELS, r)}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="hint">
        The model labels the reports and chooses which to read. Code checked every citation
        against the stored reports and decided the outcome.
      </p>
    </section>
  );
}

function Steps({ steps }: { steps: Step[] }) {
  if (steps.length === 0) return <p className="muted">No steps yet.</p>;
  return (
    <ol className="steps">
      {steps.map((step) => (
        <li key={step.seq} className={`step step-${step.kind.toLowerCase()}`}>
          <div className="entry-head">
            <strong>{KIND_LABELS[step.kind] ?? step.kind}</strong>
            {step.tool && <code>{step.tool}</code>}
            <span className="muted">{seconds(step.duration_ms)}</span>
          </div>
          {step.summary && <p>{step.summary}</p>}
          {step.input_tokens !== null && (
            <p className="muted">
              {step.input_tokens} tokens in, {step.output_tokens ?? 0} out
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

function FindingReview({
  investigation,
  onDone,
}: {
  investigation: Investigation;
  onDone: () => void;
}) {
  const api = useApi();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { review } = investigation;

  if (review) {
    return (
      <p className="status" role="status">
        {review.decision === "ACCEPTED" ? "Accepted" : "Disputed"} by {review.by},{" "}
        {formatTime(review.at)}
        {review.note && `: ${review.note}`}
      </p>
    );
  }
  if (!investigation.finding || RUNNING_STATUSES.has(investigation.status)) return null;

  async function decide(decision: "ACCEPTED" | "DISPUTED") {
    setBusy(true);
    setError(null);
    try {
      await reviewFinding(api, investigation.id, decision, note);
      onDone();
    } catch (err) {
      const code = asApiError(err).code;
      setError(
        code === "VERSION_CONFLICT"
          ? "Another reviewer already reviewed this finding."
          : "The review could not be saved. Try again.",
      );
      setBusy(false);
    }
  }

  return (
    <section className="decision" aria-labelledby="review-title">
      <h2 id="review-title">Your review</h2>
      <label htmlFor="review-note">Note (optional)</label>
      <textarea
        id="review-note"
        rows={2}
        maxLength={500}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="actions">
        <button type="button" className="primary" onClick={() => decide("ACCEPTED")} disabled={busy}>
          Accept finding
        </button>
        <button type="button" className="secondary" onClick={() => decide("DISPUTED")} disabled={busy}>
          Dispute finding
        </button>
      </div>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export function InvestigationPage() {
  const investigationId = useParams().investigationId ?? "";
  const [params] = useSearchParams();
  const api = useApi();
  const [state, retry, refresh] = useLoad(investigationId, () =>
    getInvestigation(api, investigationId),
  );

  // Each step and status change arrives as a notice; the page then reads the stored run.
  useLiveMessage((m) => {
    if (
      (m.type === "investigation.step" || m.type === "investigation.updated") &&
      m.investigation_id === investigationId
    ) {
      refresh();
    }
  });
  useLiveReconnect(refresh);

  if (state.status === "loading") {
    return (
      <section className="page">
        <div className="skeleton-title skeleton-bar" aria-hidden="true" />
        <SkeletonRows label="Loading investigation" rows={4} />
      </section>
    );
  }
  if (state.status === "error") {
    return (
      <section className="page">
        <ErrorNotice error={state.error} notFound="This investigation was not found." onRetry={retry} />
      </section>
    );
  }

  const inv = state.data;
  // A stored result served again is labeled CACHED; nothing is presented as a fresh run.
  const mode = params.get("served") === "cached" ? "CACHED" : inv.mode;
  const running = RUNNING_STATUSES.has(inv.status);
  return (
    <section className="page">
      <PageHeader
        title="Where did this report come from?"
        description={
          <>
            <span className={`tag tag-mode-${mode.toLowerCase()}`}>{mode}</span>{" "}
            {labelFor(MODE_LABELS, mode)}
          </>
        }
        actions={
          running && (
            <button type="button" className="small" onClick={refresh}>
              Refresh
            </button>
          )
        }
      />
      <p role="status">
        <span className={`status-dot ${STATUS_TONE[inv.status] ?? ""}`}>
          Status: {labelFor(INVESTIGATION_STATUS_LABELS, inv.status)}
          {running && " (this page updates as steps arrive)"}
        </span>
      </p>
      {inv.failure_reason && (
        <p className="error" role="alert">
          {labelFor(FAILURE_LABELS, inv.failure_reason)}
        </p>
      )}

      <Finding investigation={inv} />
      <FindingReview investigation={inv} onDone={refresh} />

      <h2>Steps</h2>
      <Steps steps={inv.steps} />

      <h2>Run details</h2>
      <dl className="facts panel">
        <dt>Report investigated</dt>
        <dd className="mono">{inv.claim_id}</dd>
        <dt>Model</dt>
        <dd className="mono">{inv.model_id}</dd>
        <dt>Prompt and agent</dt>
        <dd>
          {inv.prompt_version}, agent {inv.agent_version}
        </dd>
        <dt>Usage</dt>
        <dd>
          {inv.usage.model_calls} model calls, {inv.usage.tool_calls} tool calls
          {inv.usage.input_tokens !== null &&
            `, ${inv.usage.input_tokens} tokens in, ${inv.usage.output_tokens ?? 0} out`}
        </dd>
        <dt>Queued</dt>
        <dd>{formatTime(inv.timing.queued_at)}</dd>
        {inv.timing.finished_at && (
          <>
            <dt>Finished</dt>
            <dd>
              {formatTime(inv.timing.finished_at)}
              {inv.timing.duration_ms !== null && `, took ${seconds(inv.timing.duration_ms)}`}
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}
