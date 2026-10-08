/** Plain-language wording for codes the API returns. Reports are shown, never judged. */

import type { Relation } from "./api/people";

const CLAIM_TYPES: Record<string, string> = {
  MISSING: "Missing",
  FOUND_SAFE: "Found safe",
  INJURED: "Injured",
  DECEASED: "Deceased",
  SEEN_AT_LOCATION: "Seen at a location",
  SHELTERED: "Sheltered",
  OTHER: "Other information",
};

export function claimTypeLabel(code: string): string {
  if (CLAIM_TYPES[code]) return CLAIM_TYPES[code];
  const words = code.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const RELATION_LABELS: Record<Relation, string> = {
  FIRST: "First report",
  UPDATE: "Newer report",
  HISTORICAL: "Earlier report, arrived later",
  NEEDS_REVIEW: "Needs review",
  NOT_STATUS: "Other information",
};

export function relationLabel(relation: string): string {
  return RELATION_LABELS[relation as Relation] ?? relation;
}

/** Reported times in the viewer's time zone, named so nobody guesses the zone. */
export function formatTime(iso: string | null, locale?: string, timeZone?: string): string {
  if (!iso) return "Reported time unknown";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Reported time unknown";
  // dateStyle and timeStyle cannot be combined with timeZoneName, so the parts are explicit.
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
    timeZone,
  }).format(date);
}
