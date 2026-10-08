import { describe, expect, it } from "vitest";

import { claimTypeLabel, formatTime, relationLabel } from "./labels";

describe("labels", () => {
  it("words claim types plainly, including unknown ones", () => {
    expect(claimTypeLabel("FOUND_SAFE")).toBe("Found safe");
    expect(claimTypeLabel("ROAD_BLOCKED")).toBe("Road blocked");
  });

  it("words relations without judging truth", () => {
    expect(relationLabel("UPDATE")).toBe("Newer report");
    expect(relationLabel("HISTORICAL")).toBe("Earlier report, arrived later");
    expect(relationLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });

  it("names the time zone and never guesses a missing time", () => {
    expect(formatTime("2026-10-03T02:10:00Z", "en-GB", "Asia/Kolkata")).toMatch(/07:40/);
    expect(formatTime("2026-10-03T02:10:00Z", "en-GB", "UTC")).toMatch(/02:10.*UTC/);
    expect(formatTime(null)).toBe("Reported time unknown");
    expect(formatTime("not a time")).toBe("Reported time unknown");
  });
});
