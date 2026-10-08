/** Provenance investigations (design Sections 7.3 and 7.4). Reviewers and admins only. */

import type { ApiClient } from "./client";

export type InvestigationMode = "LIVE" | "CACHED" | "REPLAYED";
export type InvestigationStatus = "QUEUED" | "RUNNING" | "COMPLETED" | "NEEDS_REVIEW" | "FAILED";
export type Attribution = "DIRECT" | "RELAY" | "UNCLEAR";
export type Comparison = "SUPPORTS" | "DIFFERS" | "UNCLEAR" | "NOT_APPLICABLE";
export type StepKind = "MODEL" | "TOOL" | "GUARD" | "ERROR";

export interface StartResult {
  investigation_id: string;
  mode: InvestigationMode;
  status: InvestigationStatus;
  original_run_at?: string | null;
  ws_topic?: string;
}

export interface Citation {
  claim_id: string;
  excerpt: string;
}

export interface Finding {
  attribution: Attribution;
  referenced_source: { id: string; name: string | null } | null;
  comparison: Comparison;
  summary: string;
  citations: Citation[];
}

export interface Step {
  seq: number;
  kind: StepKind;
  tool: string | null;
  summary: string | null;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  error_code: string | null;
}

export interface Investigation {
  id: string;
  incident_id: string;
  claim_id: string;
  mode: InvestigationMode;
  status: InvestigationStatus;
  model_id: string;
  prompt_version: string;
  agent_version: string;
  finding: Finding | null;
  outcome_reasons: string[];
  failure_reason: string | null;
  usage: {
    tool_calls: number;
    model_calls: number;
    input_tokens: number | null;
    output_tokens: number | null;
    usage_source: string | null;
  };
  timing: {
    queued_at: string;
    started_at: string | null;
    finished_at: string | null;
    duration_ms: number | null;
  };
  steps: Step[];
  review: null;
}

export const RUNNING_STATUSES: ReadonlySet<InvestigationStatus> = new Set(["QUEUED", "RUNNING"]);

export function startInvestigation(
  api: ApiClient,
  claimId: string,
  forceLive = false,
): Promise<StartResult> {
  return api.post<StartResult>(
    `/v1/claims/${encodeURIComponent(claimId)}/investigations`,
    forceLive ? { force_live: true } : {},
  );
}

export function getInvestigation(api: ApiClient, investigationId: string): Promise<Investigation> {
  return api.get<Investigation>(`/v1/investigations/${encodeURIComponent(investigationId)}`);
}
