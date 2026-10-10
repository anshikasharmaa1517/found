/** People and timeline endpoints (design Sections 7.3 and 7.4). */

import type { ApiClient } from "./client";

export interface PersonRow {
  id: string;
  name: string;
  age: number | null;
}

export interface PeoplePage {
  people: PersonRow[];
  next_cursor: string | null;
}

export type Relation = "FIRST" | "UPDATE" | "HISTORICAL" | "NEEDS_REVIEW" | "NOT_STATUS";

/** A sensitive report this account may not see yet arrives as a notice only. */
export interface WithheldClaim {
  claim_id: string;
  withheld: true;
  notice: string;
}

export type Conflict =
  | { claim_id: string; claim_type: string; source: string; withheld: false }
  | WithheldClaim;

export interface Summary {
  label: string;
  basis: string;
  cited_claim_id: string | null;
  conflicts: Conflict[];
  needs_review: boolean;
}

export interface VisibleEntry {
  withheld: false;
  claim_id: string;
  seq: number;
  claim_type: string;
  value: string | null;
  source_id: string;
  source: string;
  reported_at: string | null;
  relation: Relation;
  excerpt: string;
}

export type TimelineEntry =
  | VisibleEntry
  | (WithheldClaim & { seq: number; reported_at: string | null });

/** A reviewer's decision linking this record to another. The records stay separate. */
export interface IdentityLink {
  pair_key: string;
  other_person_id: string;
  decision: "CONFIRMED" | "REJECTED";
  reviewer: string;
  decided_at: string;
}

export interface Timeline {
  person: PersonRow;
  summary: Summary;
  identity: IdentityLink[];
  entries: TimelineEntry[];
  next_cursor: string | null;
}

export type Order = "asc" | "desc";

export function listPeople(
  api: ApiClient,
  incidentId: string,
  params: { q?: string; age?: string; cursor?: string; limit?: number } = {},
): Promise<PeoplePage> {
  return api.get<PeoplePage>(`/v1/incidents/${encodeURIComponent(incidentId)}/people`, params);
}

export function getTimeline(
  api: ApiClient,
  personId: string,
  params: { order?: Order; cursor?: string; limit?: number } = {},
): Promise<Timeline> {
  return api.get<Timeline>(`/v1/people/${encodeURIComponent(personId)}/timeline`, params);
}
