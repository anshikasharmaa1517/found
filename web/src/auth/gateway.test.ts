import { describe, expect, it } from "vitest";

import { signInErrorMessage } from "./gateway";

function named(name: string): Error {
  const err = new Error("x");
  err.name = name;
  return err;
}

describe("signInErrorMessage", () => {
  it("does not reveal whether an account exists", () => {
    expect(signInErrorMessage(named("UserNotFoundException"))).toBe(
      signInErrorMessage(named("NotAuthorizedException")),
    );
  });

  it("explains throttling and password rules", () => {
    expect(signInErrorMessage(named("LimitExceededException"))).toMatch(/Too many attempts/);
    expect(signInErrorMessage(named("InvalidPasswordException"))).toMatch(/12 characters/);
  });

  it("falls back to a generic message", () => {
    expect(signInErrorMessage("boom")).toBe("Sign-in failed. Try again.");
  });
});
