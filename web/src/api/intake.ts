/** Intake: upload a file or paste text, follow the job, decide candidates (design 5.3). */

import type { ApiClient } from "./client";

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
export const UPLOAD_TYPES = ["image/jpeg", "image/png", "application/pdf"] as const;
export type UploadType = (typeof UPLOAD_TYPES)[number];

export type IntakeStatus = "RECEIVED" | "EXTRACTING" | "READY_FOR_REVIEW" | "FAILED";
export type CandidateStatus = "PENDING_REVIEW" | "CONFIRMED" | "REJECTED";

export interface IntakeJob {
  id: string;
  incident_id: string;
  organization_id: string;
  filename: string;
  content_type: string;
  status: IntakeStatus;
  sha256: string | null;
  size_bytes: number | null;
  candidate_count: number;
  dropped_count: number;
  failure_reason: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface IntakeCandidate {
  id: string;
  job_id: string;
  idx: number;
  subject_type: string;
  subject_name: string;
  age: number | null;
  claim_type: string;
  reported_at: string | null;
  location_name: string | null;
  span_text: string;
  status: CandidateStatus;
  claim_id: string | null;
  subject_id: string | null;
  decided_at: string | null;
  note: string | null;
}

export interface UploadForm {
  upload_id: string;
  post: { url: string; fields: Record<string, string> };
  max_bytes: number;
  expires_in: number;
}

export function requestUpload(
  api: ApiClient,
  incidentId: string,
  filename: string,
  contentType: UploadType,
): Promise<UploadForm> {
  return api.post<UploadForm>(`/v1/incidents/${encodeURIComponent(incidentId)}/uploads`, {
    filename,
    content_type: contentType,
    purpose: "INTAKE",
  });
}

/** Sends the file straight to storage with the presigned form; the API never sees it. */
export async function uploadFile(
  form: UploadForm,
  file: Blob,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  const data = new FormData();
  for (const [name, value] of Object.entries(form.post.fields)) data.append(name, value);
  data.append("file", file);
  const response = await fetchImpl(form.post.url, { method: "POST", body: data });
  if (!response.ok) throw new Error(`Upload failed with status ${response.status}.`);
}

export function submitText(
  api: ApiClient,
  incidentId: string,
  text: string,
): Promise<{ job: IntakeJob }> {
  return api.post<{ job: IntakeJob }>(
    `/v1/incidents/${encodeURIComponent(incidentId)}/intake-text`,
    { text },
  );
}

export function getIntakeJob(
  api: ApiClient,
  jobId: string,
): Promise<{ job: IntakeJob; candidates: IntakeCandidate[] }> {
  return api.get(`/v1/intake-jobs/${encodeURIComponent(jobId)}`);
}

export interface CandidateDecision {
  decision: "CONFIRMED" | "REJECTED";
  note?: string;
  person_id?: string;
  edits?: { claim_type?: string };
}

export function decideCandidate(
  api: ApiClient,
  candidateId: string,
  body: CandidateDecision,
): Promise<{ candidate: IntakeCandidate }> {
  return api.post(`/v1/intake-candidates/${encodeURIComponent(candidateId)}/decision`, body);
}
