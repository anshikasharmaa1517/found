/** People and timeline endpoints (design Sections 7.3 and 7.4). */

import type { ApiClient } from "./client";
import type { SourceType } from "./sources";

/** A person's cited status, as the list shows it; masked for roles that may not see it. */
export interface PersonStatus {
  label: string;
  claim_type: string | null;
  needs_review: boolean;
  conflicts: number;
  report_count: number;
  withheld: boolean;
}

export interface PersonRow {
  id: string;
  name: string;
  age: number | null;
  status?: PersonStatus | null;
}

export interface PeopleStats {
  people: number;
  by_status: Record<string, number>;
  disagree: number;
  needs_review: number;
  matches_open: number;
  matches_decided: number;
}

export function getPeopleStats(api: ApiClient, incidentId: string): Promise<PeopleStats> {
  return api.get<PeopleStats>(`/v1/incidents/${encodeURIComponent(incidentId)}/people/stats`);
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
  /** What kind of organization the source is, for "From X (Police)". */
  source_type?: SourceType | null;
  reported_at: string | null;
  /** When Found received the report, which can differ from when it says it happened. */
  ingested_at?: string;
  /** The source's own id for the report. */
  external_reference?: string;
  /** Where the report was made, when it named a place. */
  location?: { id: string; name: string } | null;
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
