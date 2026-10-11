import type { TimelineEntry, VisibleEntry } from "./api/people";

export function entryAnchor(claimId: string): string {
  return `entry-${claimId}`;
}

/**
 * For each report, the type of the report before it in time, when the two differ. Reports
 * this account may not see are skipped, so their type never shows through a neighbour.
 */
export function statusChanges(
  entries: TimelineEntry[],
  newestFirst: boolean,
): Map<string, string> {
  const inTime = newestFirst ? [...entries].reverse() : entries;
  const changes = new Map<string, string>();
  let previous: VisibleEntry | null = null;
  for (const entry of inTime) {
    if (entry.withheld) continue;
    if (previous && previous.claim_type !== entry.claim_type) {
      changes.set(entry.claim_id, previous.claim_type);
    }
    previous = entry;
  }
  return changes;
}
