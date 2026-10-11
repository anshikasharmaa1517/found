/** The incident and its newest reports, for the overview page. */

import type { ApiClient } from "./client";

/** A river's course from open map data. It is never the extent of a flood. */
export interface RiverCourse {
  name: string;
  note: string;
  attribution: string;
  /** [lon, lat] points, upstream first. */
  coordinates: [number, number][];
}

/** A line from open map data, drawn only for context: another river, or a boundary. */
export interface MapLine {
  name: string | null;
  /** [lon, lat] points; a boundary ends where it starts. */
  coordinates: [number, number][];
}

/** Nearby rivers and the district around the incident, for orientation on the map. */
export interface MapContext {
  attribution: string;
  rivers: MapLine[];
  district: MapLine | null;
}

export interface IncidentInfo {
  id: string;
  name: string;
  area: string | null;
  is_demo: boolean;
  started_at: string | null;
  river?: RiverCourse | null;
  map_context?: MapContext | null;
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
