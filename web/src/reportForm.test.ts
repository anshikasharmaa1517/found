import { describe, expect, it } from "vitest";

import {
  buildBody,
  errorsFromApi,
  formatOffset,
  toOffsetIso,
  validate,
  type ReportValues,
} from "./reportForm";

const NEW_PERSON: ReportValues = {
  subjectMode: "new",
  personId: "",
  name: "  Maya Rawat ",
  age: "24",
  notes: "",
  claimType: "MISSING",
  value: "",
  originalText: " Family reports Maya Rawat, 24, missing. ",
  reference: "UKPD-FIR-0091",
  reportedAt: "2026-10-02T21:10",
  timeUnknown: false,
};

const IST = () => 330;

describe("time conversion", () => {
  it("keeps the local time and adds the offset", () => {
    expect(formatOffset(330)).toBe("+05:30");
    expect(formatOffset(-240)).toBe("-04:00");
    expect(formatOffset(0)).toBe("+00:00");
    expect(toOffsetIso("2026-10-03T07:40", 330)).toBe("2026-10-03T07:40:00+05:30");
  });
});

describe("validate", () => {
  it("accepts a complete report", () => {
    expect(validate(NEW_PERSON)).toEqual({});
  });

  it("explains each problem next to its field", () => {
    const errors = validate({
      ...NEW_PERSON,
      name: " ",
      age: "130",
      claimType: "ROAD_BLOCKED",
      originalText: "",
      reference: "bad ref!",
      reportedAt: "",
    });
    expect(Object.keys(errors).sort()).toEqual(
      ["age", "claimType", "name", "originalText", "reference", "reportedAt"].sort(),
    );
  });

  it("needs a chosen person for an existing subject", () => {
    expect(validate({ ...NEW_PERSON, subjectMode: "existing" }).personId).toBeTruthy();
  });

  it("allows an unknown time", () => {
    expect(validate({ ...NEW_PERSON, reportedAt: "", timeUnknown: true })).toEqual({});
  });

  it("enforces the API's length limits", () => {
    expect(validate({ ...NEW_PERSON, originalText: "x".repeat(4001) }).originalText).toMatch(/4000/);
    expect(validate({ ...NEW_PERSON, value: "x".repeat(501) }).value).toMatch(/500/);
  });
});

describe("buildBody", () => {
  it("builds a new-person report with trimmed text and the reported offset", () => {
    expect(buildBody(NEW_PERSON, IST)).toEqual({
      subject: { type: "PERSON", new: { name: "Maya Rawat", age: 24 } },
      claim_type: "MISSING",
      original_text: "Family reports Maya Rawat, 24, missing.",
      external_reference: "UKPD-FIR-0091",
      reported_at: "2026-10-02T21:10:00+05:30",
    });
  });

  it("refers to an existing person and leaves out an unknown time", () => {
    const body = buildBody(
      { ...NEW_PERSON, subjectMode: "existing", personId: "per_1", value: " Stable ", timeUnknown: true },
      IST,
    );
    expect(body.subject).toEqual({ type: "PERSON", id: "per_1" });
    expect(body.value).toBe("Stable");
    expect("reported_at" in body).toBe(false);
  });
});

describe("errorsFromApi", () => {
  it("maps API fields to inputs and keeps the rest for the form", () => {
    expect(
      errorsFromApi({
        errors: [
          { field: "subject.new.name", message: "Too long." },
          { field: "", message: "Value error, claim_type X is not valid." },
          { field: "org_id", message: "Set from your sign-in." },
        ],
      }),
    ).toEqual({
      name: "Too long.",
      form: "Value error, claim_type X is not valid. Set from your sign-in.",
    });
  });

  it("copes with a missing list", () => {
    expect(errorsFromApi({})).toEqual({});
  });
});
