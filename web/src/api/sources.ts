/** Who published in an incident, and how much. */

import type { ApiClient } from "./client";

export type SourceType =
  | "POLICE"
  | "HOSPITAL"
  | "NGO"
  | "GOVERNMENT"
  | "SHELTER_OPERATOR"
  | "COMMUNITY";

/** Counts by report type; reports a reviewer still holds are counted under WITHHELD. */
export interface SourceSummary {
  id: string;
  name: string;
  source_type: SourceType;
  organization_id: string | null;
  reports: number;
  by_type: Record<string, number>;
  /** Reports from other sources that name this one: relays, not independent checks. */
  cited_by: number;
  latest_at: string | null;
}

export const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  POLICE: "Police",
  HOSPITAL: "Hospital",
  NGO: "Aid group",
  GOVERNMENT: "Government",
  SHELTER_OPERATOR: "Shelter operator",
  COMMUNITY: "Community member",
};

export const WITHHELD = "WITHHELD";

export function listSources(
  api: ApiClient,
  incidentId: string,
): Promise<{ sources: SourceSummary[] }> {
  return api.get(`/v1/incidents/${encodeURIComponent(incidentId)}/sources`);
}
