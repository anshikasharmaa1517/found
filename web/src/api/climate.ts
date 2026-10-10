/** Climate layers: roads, bridges, shelters, aid points, hazards and places (UC-7). */

import type { ApiClient } from "./client";

export type ClimateType = "INFRASTRUCTURE" | "SHELTER" | "AID_POINT" | "HAZARD" | "PLACE";

export interface FeatureReport {
  claim_id: string;
  claim_type: string;
  source: string;
  reported_at: string | null;
  excerpt: string;
}

export interface ClimateFeature {
  subject_id: string;
  subject_type: ClimateType;
  name: string;
  label: string;
  basis: string;
  cited_claim_id: string | null;
  needs_review: boolean;
  report_count: number;
  location: { location_id: string; name: string; lat: number | null; lon: number | null } | null;
  /** The latest report from each other source that says something different. */
  conflicts: FeatureReport[];
  recent: FeatureReport[];
}

export interface ClimateLayer {
  features: ClimateFeature[];
  caveat: string;
  updated_at: string;
}

export const CLIMATE_TYPE_LABELS: Record<ClimateType, string> = {
  INFRASTRUCTURE: "Roads and bridges",
  SHELTER: "Shelters",
  AID_POINT: "Aid points",
  HAZARD: "Hazards",
  PLACE: "Places",
};

export const CLIMATE_TYPES = Object.keys(CLIMATE_TYPE_LABELS) as ClimateType[];

export function getClimateLayer(api: ApiClient, incidentId: string): Promise<ClimateLayer> {
  return api.get<ClimateLayer>(`/v1/incidents/${encodeURIComponent(incidentId)}/climate`);
}

export function plotted(feature: ClimateFeature): feature is ClimateFeature & {
  location: { location_id: string; name: string; lat: number; lon: number };
} {
  return feature.location?.lat != null && feature.location?.lon != null;
}
