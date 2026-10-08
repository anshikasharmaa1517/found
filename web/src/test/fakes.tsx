import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { ApiClient } from "../api/client";
import { ApiContext } from "../api/context";
import { AppRoutes } from "../App";
import { AuthProvider } from "../auth/AuthProvider";
import type { AuthGateway, SignInStep } from "../auth/gateway";
import { userFromClaims, type User } from "../auth/user";

export const REVIEWER: User = userFromClaims({
  sub: "u1",
  email: "ananya@example.org",
  name: "Ananya",
  "cognito:groups": ["reviewer"],
});

/** A sign-in provider with scripted answers. */
export class FakeGateway implements AuthGateway {
  user: User | null = null;
  signInSteps: (SignInStep | Error)[] = [];
  respondSteps: (SignInStep | Error)[] = [];
  answers: string[] = [];
  signedInAs: User = REVIEWER;

  async currentUser() {
    return this.user;
  }
  async idToken() {
    return this.user ? "token" : null;
  }
  async signIn() {
    return this.next(this.signInSteps);
  }
  async respond(answer: string) {
    this.answers.push(answer);
    return this.next(this.respondSteps);
  }
  async signOut() {
    this.user = null;
  }
  private next(steps: (SignInStep | Error)[]): SignInStep {
    const step = steps.shift() ?? { kind: "done" };
    if (step instanceof Error) throw step;
    if (step.kind === "done") this.user = this.signedInAs;
    return step;
  }
}

export function fakeApi(health: "ok" | "down" = "ok"): ApiClient {
  return {
    get: async <T,>() => {
      if (health === "down") throw new Error("down");
      return { status: "ok" } as T;
    },
    post: async <T,>() => ({}) as T,
    del: async () => undefined,
  };
}

export function renderApp(
  gateway: AuthGateway,
  path = "/",
  api: ApiClient = fakeApi(),
) {
  return render(
    <AuthProvider gateway={gateway}>
      <ApiContext.Provider value={api}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </ApiContext.Provider>
    </AuthProvider>,
  );
}
