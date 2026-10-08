/** The review queue and reviewer decisions (design Sections 7.4 and 9.6). */

import type { ApiClient } from "./client";

export type ReviewType = "conflict" | "held_alert" | "finding" | "identity" | "intake";
export type ReviewStatus = "OPEN" | "DONE";

export interface ReviewItem {
  id: string;
  type: ReviewType;
  status: ReviewStatus;
  priority: number;
  created_at: string;
  ref_id: string;
  resolved_by: string | null;
  resolved_at: string | null;
  note: string | null;
  person: { id: string; name: string; age: number | null } | null;
  claim: {
    id: string;
    claim_type: string;
    source: string;
    reported_at: string | null;
    excerpt: string;
  } | null;
  investigation: {
    id: string;
    status: string;
    attribution: string | null;
    comparison: string | null;
    outcome_reasons: string[];
  } | null;
}

export interface ReviewPage {
  items: ReviewItem[];
  next_cursor: string | null;
}

export interface ResolveResult {
  id: string;
  status: ReviewStatus;
  resolved_by: string;
  alerts_released: number;
}

export function listReviewQueue(
  api: ApiClient,
  incidentId: string,
  params: { type?: ReviewType; status?: ReviewStatus; cursor?: string } = {},
): Promise<ReviewPage> {
  return api.get<ReviewPage>(
    `/v1/incidents/${encodeURIComponent(incidentId)}/review-queue`,
    params,
  );
}

export function resolveReviewItem(
  api: ApiClient,
  incidentId: string,
  reviewId: string,
  note: string,
): Promise<ResolveResult> {
  return api.post<ResolveResult>(
    `/v1/incidents/${encodeURIComponent(incidentId)}/review-items/${encodeURIComponent(reviewId)}/resolve`,
    note.trim() ? { note: note.trim() } : {},
  );
}

export function reviewFinding<T>(
  api: ApiClient,
  investigationId: string,
  decision: "ACCEPTED" | "DISPUTED",
  note: string,
): Promise<T> {
  return api.post<T>(`/v1/investigations/${encodeURIComponent(investigationId)}/review`, {
    decision,
    ...(note.trim() ? { note: note.trim() } : {}),
  });
}
