import { describe, expect, it } from "vitest";

import type { TimelineEntry, VisibleEntry } from "./api/people";
import { statusChanges } from "./timeline";

function report(id: string, claimType: string): VisibleEntry {
  return {
    withheld: false,
    claim_id: id,
    seq: 1,
    claim_type: claimType,
    value: null,
    source_id: "src",
    source: "Source",
    reported_at: null,
    relation: "UPDATE",
    excerpt: "",
  };
}

const HELD: TimelineEntry = { withheld: true, claim_id: "held", seq: 2, reported_at: null, notice: "n" };

describe("statusChanges", () => {
  it("marks a report whose type differs from the one before it in time", () => {
    const entries = [report("a", "MISSING"), report("b", "MISSING"), report("c", "FOUND_SAFE")];
    expect([...statusChanges(entries, false)]).toEqual([["c", "MISSING"]]);
    expect([...statusChanges([...entries].reverse(), true)]).toEqual([["c", "MISSING"]]);
  });

  it("never lets a hidden report show through its neighbour", () => {
    const entries = [report("a", "MISSING"), HELD, report("c", "FOUND_SAFE")];
    expect([...statusChanges(entries, false)]).toEqual([["c", "MISSING"]]);
    expect(statusChanges([HELD], false).size).toBe(0);
  });
});
