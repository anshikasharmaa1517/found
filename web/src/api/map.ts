/** Report counts per reported place (design Section 7.3). */

import type { ApiClient } from "./client";

export type MapBucket = "MISSING" | "FOUND_SAFE" | "NEEDS_REVIEW" | "OTHER";

export interface MapPlace {
  location_id: string;
  name: string;
  lat: number;
  lon: number;
  reports: number;
  by_status: Record<MapBucket, number>;
}

export interface IncidentMap {
  places: MapPlace[];
  located_reports: number;
  unlocated_reports: number;
  caveat: string;
  updated_at: string;
}

export const BUCKET_LABELS: Record<MapBucket, string> = {
  MISSING: "Missing",
  FOUND_SAFE: "Found safe",
  NEEDS_REVIEW: "Needs review",
  OTHER: "Other",
};

export const BUCKETS = Object.keys(BUCKET_LABELS) as MapBucket[];

/** What a place's pin shows: one status, most urgent first; the counts say the rest. */
export type PlaceStatus = "MISSING" | "NEEDS_REVIEW" | "FOUND_SAFE" | "NONE";

export const PLACE_STATUS_LABELS: Record<PlaceStatus, string> = {
  MISSING: "Missing",
  NEEDS_REVIEW: "Needs review",
  FOUND_SAFE: "Reported safe",
  NONE: "No current status",
};

export function placeStatus(place: MapPlace): PlaceStatus {
  if (place.by_status.MISSING > 0) return "MISSING";
  if (place.by_status.NEEDS_REVIEW > 0) return "NEEDS_REVIEW";
  if (place.by_status.FOUND_SAFE > 0) return "FOUND_SAFE";
  return "NONE";
}

export function getIncidentMap(api: ApiClient, incidentId: string): Promise<IncidentMap> {
  return api.get<IncidentMap>(`/v1/incidents/${encodeURIComponent(incidentId)}/map`);
}

/** Amazon Location basemap style; the key only reads tiles for this app's origins. */
export function mapStyleUrl(region: string, apiKey: string, dark = false): string {
  const params = new URLSearchParams({ key: apiKey });
  if (dark) params.set("color-scheme", "Dark");
  return `https://maps.geo.${region}.amazonaws.com/v2/styles/Standard/descriptor?${params}`;
}
