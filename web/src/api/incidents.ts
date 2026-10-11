/** The incident and its newest reports, for the overview page. */

import type { ApiClient } from "./client";

export interface IncidentInfo {
  id: string;
  name: string;
  area: string | null;
  is_demo: boolean;
  started_at: string | null;
}

interface RecentBase {
  claim_id: string;
  subject_id: string;
  subject_type: string;
  subject_name: string | null;
  ingested_at: string;
}

/** A sensitive report this account may not see yet arrives as a notice only. */
export type RecentReport =
  | (RecentBase & {
      withheld: false;
      claim_type: string;
      source: string;
      reported_at: string | null;
      excerpt: string;
    })
  | (RecentBase & { withheld: true; notice: string });

export function getIncident(api: ApiClient, incidentId: string): Promise<IncidentInfo> {
  return api.get<IncidentInfo>(`/v1/incidents/${encodeURIComponent(incidentId)}`);
}

export function getRecentReports(
  api: ApiClient,
  incidentId: string,
  limit = 8,
  sourceId?: string,
): Promise<{ reports: RecentReport[] }> {
  return api.get(`/v1/incidents/${encodeURIComponent(incidentId)}/recent`, {
    limit,
    source_id: sourceId,
  });
}
