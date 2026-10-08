/** Publishing a structured report (design Section 7.3). */

import type { ApiClient } from "./client";

export type ReportSubject =
  | { type: "PERSON"; id: string }
  | { type: "PERSON"; new: { name: string; age?: number; notes?: string } };

export interface ReportBody {
  subject: ReportSubject;
  claim_type: string;
  value?: string;
  original_text: string;
  external_reference: string;
  reported_at?: string;
  location?: { name: string; lat?: number; lon?: number };
}

export interface PublishedClaim {
  id: string;
  incident_id: string;
  subject_id: string;
  source: { id: string; name: string; type: string };
  seq: number;
  claim_type: string;
  reported_at: string | null;
  ingested_at: string;
}

export interface PublishResult {
  claim: PublishedClaim;
  replayed: boolean;
}

export function publishReport(
  api: ApiClient,
  incidentId: string,
  body: ReportBody,
): Promise<PublishResult> {
  return api.post<PublishResult>(`/v1/incidents/${encodeURIComponent(incidentId)}/reports`, body);
}
