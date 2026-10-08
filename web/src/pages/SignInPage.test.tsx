import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { userFromClaims } from "../auth/user";
import { FakeGateway, REVIEWER, fakeApi, renderApp } from "../test/fakes";

function named(name: string): Error {
  const err = new Error(name);
  err.name = name;
  return err;
}

async function signIn(user = userEvent.setup()) {
  await user.type(await screen.findByLabelText("Email"), "ananya@example.org");
  await user.type(screen.getByLabelText("Password"), "correct horse 1A");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return user;
}

describe("sign-in", () => {
  it("sends signed-out visitors to the sign-in page", async () => {
    renderApp(new FakeGateway(), "/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("signs in and shows the home page with role and service status", async () => {
    renderApp(new FakeGateway(), "/");
    await signIn();
    expect(await screen.findByRole("heading", { name: "Welcome, Ananya" })).toBeInTheDocument();
    expect(screen.getAllByText("Reviewer").length).toBeGreaterThan(0);
    expect(await screen.findByText(/Service: available/)).toBeInTheDocument();
  });

  it("shows a plain error for wrong credentials", async () => {
    const gateway = new FakeGateway();
    gateway.signInSteps = [named("NotAuthorizedException")];
    renderApp(gateway, "/");
    await signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is incorrect.");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("asks a first-time user for a new password and checks they match", async () => {
    const gateway = new FakeGateway();
    gateway.signInSteps = [{ kind: "newPassword" }];
    renderApp(gateway, "/");
    const user = await signIn();
    expect(
      await screen.findByRole("heading", { name: "Choose a new password" }),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText("New password"), "BrandNewPass123");
    await user.type(screen.getByLabelText("Repeat new password"), "BrandNewPass124");
    await user.click(screen.getByRole("button", { name: "Save and sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
    expect(gateway.answers).toEqual([]);

    await user.clear(screen.getByLabelText("Repeat new password"));
    await user.type(screen.getByLabelText("Repeat new password"), "BrandNewPass123");
    await user.click(screen.getByRole("button", { name: "Save and sign in" }));
    expect(await screen.findByRole("heading", { name: "Welcome, Ananya" })).toBeInTheDocument();
    expect(gateway.answers).toEqual(["BrandNewPass123"]);
  });

  it("asks for a one-time code when the account uses an authenticator", async () => {
    const gateway = new FakeGateway();
    gateway.signInSteps = [{ kind: "totp" }];
    gateway.respondSteps = [named("CodeMismatchException")];
    renderApp(gateway, "/");
    const user = await signIn();
    const code = await screen.findByLabelText(/Six-digit code/);
    await user.type(code, "123456");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That code is not right.");
    await user.clear(code);
    await user.type(code, "654321");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("heading", { name: "Welcome, Ananya" })).toBeInTheDocument();
  });

  it("explains unsupported steps instead of failing silently", async () => {
    const gateway = new FakeGateway();
    gateway.signInSteps = [{ kind: "unsupported", step: "CONTINUE_SIGN_IN_WITH_TOTP_SETUP" }];
    renderApp(gateway, "/");
    await signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent("Ask an admin.");
  });

  it("returns to the page the user first asked for", async () => {
    renderApp(new FakeGateway(), "/somewhere");
    await signIn();
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });

  it("sends signed-in users away from the sign-in page", async () => {
    const gateway = new FakeGateway();
    gateway.user = REVIEWER;
    renderApp(gateway, "/sign-in");
    expect(await screen.findByRole("heading", { name: "Welcome, Ananya" })).toBeInTheDocument();
  });

  it("tells users without a role to ask an admin", async () => {
    const gateway = new FakeGateway();
    gateway.user = userFromClaims({ sub: "u9", email: "new@example.org" });
    renderApp(gateway, "/");
    expect(await screen.findByRole("heading", { name: "No role assigned" })).toBeInTheDocument();
  });

  it("signs out back to the sign-in page", async () => {
    const gateway = new FakeGateway();
    gateway.user = REVIEWER;
    renderApp(gateway, "/");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(gateway.user).toBeNull();
  });

  it("says when the service is not reachable", async () => {
    const gateway = new FakeGateway();
    gateway.user = REVIEWER;
    renderApp(gateway, "/", fakeApi("down"));
    expect(await screen.findByText(/Service: not reachable/)).toBeInTheDocument();
  });
});
