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

/** Investigations: what the model labeled, in plain words, and what code decided. */
export const ATTRIBUTION_LABELS: Record<string, string> = {
  DIRECT: "First-hand: the source reports what it saw or handled",
  RELAY: "Relayed: it passes on another source's report",
  UNCLEAR: "Unclear where the information came from",
};

export const COMPARISON_LABELS: Record<string, string> = {
  SUPPORTS: "Matches the named source's own reports",
  DIFFERS: "Differs from the named source's own reports",
  UNCLEAR: "Could not be compared clearly",
  NOT_APPLICABLE: "Nothing to compare",
};

export const INVESTIGATION_STATUS_LABELS: Record<string, string> = {
  QUEUED: "Queued",
  RUNNING: "Running",
  COMPLETED: "Completed",
  NEEDS_REVIEW: "Needs a reviewer",
  FAILED: "Failed",
};

export const MODE_LABELS: Record<string, string> = {
  LIVE: "Live run",
  CACHED: "Cached result: same evidence as a stored run, no new model call",
  REPLAYED: "Replayed: a recorded run restored for the demo",
};

export const REASON_LABELS: Record<string, string> = {
  RELAY_NOT_FIRST_HAND: "A relay is not independent confirmation, even when it agrees.",
  RELAY_DIFFERS_FROM_SOURCE: "The relay differs from what its source reported.",
  COMPARISON_UNCLEAR: "The accounts could not be compared clearly.",
  SOURCE_NOT_FOUND: "The report relays a source that has no reports here.",
  ATTRIBUTION_UNCLEAR: "It is unclear where the report got its information.",
  DIRECT_BUT_NAMES_SOURCE: "The report reads as first-hand but names another source.",
};

export const FAILURE_LABELS: Record<string, string> = {
  NO_FINDING: "The run ended without recording a finding.",
  TURN_LIMIT: "The run reached its limit of model turns.",
  TIMEOUT: "The run reached its time limit.",
  MODEL_CALL_CAP: "The monthly model call budget is used up.",
  VERSION_MISMATCH: "The agent ran different versions than recorded, so the run was stopped.",
  AGENT_UNAVAILABLE: "The agent could not be reached.",
  AGENT_ERROR: "The agent stopped with an error.",
  RUNNER_INTERRUPTED: "The run was interrupted and was not repeated.",
  RUNNER_ERROR: "The run could not be processed.",
  QUEUE_UNAVAILABLE: "The run could not be queued.",
};

export function labelFor(labels: Record<string, string>, code: string): string {
  return labels[code] ?? code;
}
