import { useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../api/context";
import {
  getInvestigation,
  RUNNING_STATUSES,
  type Investigation,
  type Step,
} from "../api/investigations";
import { ErrorNotice } from "../components/ErrorNotice";
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
import { useLoad } from "../useLoad";

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
            <p className="muted">Report {c.claim_id}</p>
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

  if (state.status === "loading") return <p className="page-status">Loading investigation</p>;
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
      <h1>Where did this report come from?</h1>
      <p>
        <span className={`tag tag-mode-${mode.toLowerCase()}`}>{mode}</span>{" "}
        <span className="muted">{labelFor(MODE_LABELS, mode)}</span>
      </p>
      <p className="status" role="status">
        Status: {labelFor(INVESTIGATION_STATUS_LABELS, inv.status)}
        {running && " (this page updates as steps arrive)"}
      </p>
      {running && (
        <button type="button" onClick={refresh}>
          Refresh
        </button>
      )}
      {inv.failure_reason && (
        <p className="error" role="alert">
          {labelFor(FAILURE_LABELS, inv.failure_reason)}
        </p>
      )}

      <Finding investigation={inv} />

      <h2>Steps</h2>
      <Steps steps={inv.steps} />

      <h2>Run details</h2>
      <dl className="facts">
        <dt>Report investigated</dt>
        <dd>{inv.claim_id}</dd>
        <dt>Model</dt>
        <dd>{inv.model_id}</dd>
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
