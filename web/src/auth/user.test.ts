import { describe, expect, it } from "vitest";

import { displayName, hasRole, initials, mainRole, userFromClaims } from "./user";

describe("userFromClaims", () => {
  it("reads identity, organization and known roles in precedence order", () => {
    const user = userFromClaims({
      sub: "u1",
      email: "asha@example.org",
      "cognito:groups": ["publisher", "unknown", "reviewer"],
      "custom:org_id": "org_h",
    });
    expect(user).toEqual({
      id: "u1",
      email: "asha@example.org",
      name: null,
      roles: ["reviewer", "publisher"],
      orgId: "org_h",
    });
    expect(mainRole(user)).toBe("reviewer");
    expect(hasRole(user, "family", "publisher")).toBe(true);
    expect(hasRole(user, "admin")).toBe(false);
  });

  it("treats missing groups as no role", () => {
    const user = userFromClaims({ sub: "u2" });
    expect(user.roles).toEqual([]);
    expect(mainRole(user)).toBeNull();
    expect(displayName(user)).toBe("Signed in");
  });

  it("prefers the name, then the email, for display", () => {
    expect(displayName(userFromClaims({ sub: "u", name: "Asha", email: "a@x.org" }))).toBe("Asha");
    expect(displayName(userFromClaims({ sub: "u", email: "a@x.org" }))).toBe("a@x.org");
  });
});

describe("initials", () => {
  it("uses the first and last initial, or the first two letters", () => {
    expect(initials("Ananya Rao")).toBe("AR");
    expect(initials("Maya Devi Rawat")).toBe("MR");
    expect(initials("asha")).toBe("AS");
    expect(initials("reviewer@example.com")).toBe("RE");
  });
});
