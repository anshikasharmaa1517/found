import { afterEach, describe, expect, it } from "vitest";

import { isIncidentId, rememberedIncident, rememberIncident } from "./incident";

afterEach(() => localStorage.clear());

describe("incident memory", () => {
  it("accepts only id-shaped values", () => {
    expect(isIncidentId("inc_01J9X0")).toBe(true);
    expect(isIncidentId("../admin")).toBe(false);
    expect(isIncidentId("")).toBe(false);
  });

  it("prefers the last opened incident, then the configured default", () => {
    expect(rememberedIncident()).toBeNull();
    expect(rememberedIncident("inc_demo")).toBe("inc_demo");
    rememberIncident("inc_1");
    expect(rememberedIncident("inc_demo")).toBe("inc_1");
  });

  it("ignores tampered storage", () => {
    localStorage.setItem("found.incidentId", "<script>");
    expect(rememberedIncident("inc_demo")).toBe("inc_demo");
  });
});
