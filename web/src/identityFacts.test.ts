import { describe, expect, it } from "vitest";

import type { Timeline } from "./api/people";
import { compareRecords } from "./identityFacts";

function record(
  name: string,
  age: number | null,
  label: string,
  place: string | null = null,
): Timeline {
  return {
    person: { id: name, name, age },
    summary: { label, basis: "", cited_claim_id: null, conflicts: [], needs_review: false },
    identity: [],
    entries: [
      {
        withheld: false,
        claim_id: `clm_${name}`,
        seq: 1,
        claim_type: "MISSING",
        value: null,
        source_id: "src",
        source: "Source",
        reported_at: null,
        relation: "FIRST",
        excerpt: "",
        location: place ? { id: `loc_${place}`, name: place } : null,
      },
    ],
    next_cursor: null,
  };
}

describe("compareRecords", () => {
  it("treats a matching initial as unknown, not a difference", () => {
    const facts = compareRecords(
      ["GIVEN_EXACT", "AGE_EQUAL"],
      record("Sita Tamang", 24, "Reported found safe", "Old Bridge"),
      record("Sita T.", 24, "No status yet", "Old Bridge"),
    );
    expect(facts.similarities).toEqual(["Same given name", "Same age"]);
    expect(facts.differences).toEqual([
      "Latest reports differ: Reported found safe and No status yet",
    ]);
    expect(facts.unknowns).toEqual(["Sita T. gives only an initial for the surname"]);
  });

  it("lists real differences and what neither record says", () => {
    const facts = compareRecords(
      ["GIVEN_EXACT"],
      record("Sita Tamang", 24, "Reported missing", "Old Bridge"),
      record("Sita Gurung", null, "Reported missing"),
    );
    expect(facts.differences).toEqual(["Surnames differ: Tamang and Gurung"]);
    expect(facts.unknowns).toEqual(["Age not reported for Sita Gurung", "No place reported for Sita Gurung"]);
  });

  it("flags different ages, places and a mismatched initial", () => {
    const facts = compareRecords(
      [],
      record("Sita Tamang", 24, "Reported missing", "Old Bridge"),
      record("Sita G.", 30, "Reported missing", "Market Ghat"),
    );
    expect(facts.differences).toEqual([
      "Ages differ: 24 and 30",
      "Surname initial does not match: Sita Tamang and Sita G.",
      "Reported at different places: Old Bridge and Market Ghat",
    ]);
  });
});
