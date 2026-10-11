/**
 * What two records share, where they differ, and what neither says, for a reviewer
 * deciding a proposed match (as in Trace's match review). Read from stored fields only;
 * nothing here decides the match or scores it.
 */

import type { Timeline, VisibleEntry } from "./api/people";
import { labelFor, MATCH_REASON_LABELS } from "./labels";

export interface RecordFacts {
  similarities: string[];
  differences: string[];
  unknowns: string[];
}

function surname(name: string): string | null {
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? parts[parts.length - 1]! : null;
}

function isInitial(part: string): boolean {
  return /^[A-Za-z]\.?$/.test(part);
}

function places(t: Timeline): string[] {
  const names = t.entries
    .filter((e): e is VisibleEntry => !e.withheld)
    .map((e) => e.location?.name)
    .filter((n): n is string => Boolean(n));
  return [...new Set(names)];
}

export function compareRecords(reasons: string[], a: Timeline, b: Timeline): RecordFacts {
  const differences: string[] = [];
  const unknowns: string[] = [];
  const nameA = a.person.name;
  const nameB = b.person.name;

  // Ages.
  if (a.person.age !== null && b.person.age !== null && a.person.age !== b.person.age) {
    differences.push(`Ages differ: ${a.person.age} and ${b.person.age}`);
  }
  for (const t of [a, b]) {
    if (t.person.age === null) unknowns.push(`Age not reported for ${t.person.name}`);
  }

  // Surnames: an initial is not a difference, but it is not a full name either.
  const sa = surname(nameA);
  const sb = surname(nameB);
  if (sa && sb) {
    const initialA = isInitial(sa);
    const initialB = isInitial(sb);
    if (initialA !== initialB) {
      const [short, full] = initialA ? [nameA, sb] : [nameB, sa];
      if (full.charAt(0).toUpperCase() === (initialA ? sa : sb).charAt(0).toUpperCase()) {
        unknowns.push(`${short} gives only an initial for the surname`);
      } else {
        differences.push(`Surname initial does not match: ${nameA} and ${nameB}`);
      }
    } else if (!initialA && sa.toLowerCase() !== sb.toLowerCase()) {
      differences.push(`Surnames differ: ${sa} and ${sb}`);
    }
  } else {
    for (const [name, part] of [
      [nameA, sa],
      [nameB, sb],
    ] as const) {
      if (!part) unknowns.push(`No surname reported for ${name}`);
    }
  }

  // What each record's latest report says.
  if (a.summary.label !== b.summary.label) {
    differences.push(`Latest reports differ: ${a.summary.label} and ${b.summary.label}`);
  }

  // Places.
  const pa = places(a);
  const pb = places(b);
  if (pa.length > 0 && pb.length > 0 && !pa.some((p) => pb.includes(p))) {
    differences.push(`Reported at different places: ${pa.join(", ")} and ${pb.join(", ")}`);
  }
  for (const [t, p] of [
    [a, pa],
    [b, pb],
  ] as const) {
    if (p.length === 0) unknowns.push(`No place reported for ${t.person.name}`);
  }

  return {
    similarities: reasons.map((r) => labelFor(MATCH_REASON_LABELS, r)),
    differences,
    unknowns,
  };
}
