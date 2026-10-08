import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ApiError, type ApiClient } from "../api/client";
import { ApiContext } from "../api/context";
import { AppRoutes, type AppSettings } from "../App";
import { AuthProvider } from "../auth/AuthProvider";
import type { AuthGateway, SignInStep } from "../auth/gateway";
import { userFromClaims, type User } from "../auth/user";
import type { SocketLike } from "../live/client";

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

export type Query = Record<string, string | number | undefined>;
export interface Call {
  path: string;
  query: Query;
}

export interface Post {
  path: string;
  body: unknown;
}

/**
 * Answers requests by path and records every call. A handler may throw, for example an
 * ApiError, to stand in for an error response.
 */
export function routedApi(
  routes: Record<string, (query: Query) => unknown>,
  posts: Record<string, (body: unknown) => unknown> = {},
  deletes: Record<string, () => void> = {},
) {
  const calls: Call[] = [];
  const sent: Post[] = [];
  const api: ApiClient = {
    get: async <T,>(path: string, query: Query = {}) => {
      calls.push({ path, query });
      const handler = routes[path];
      if (!handler) throw new ApiError(404, "NOT_FOUND", "Not found.");
      return handler(query) as T;
    },
    post: async <T,>(path: string, body: unknown = {}) => {
      sent.push({ path, body });
      const handler = posts[path];
      if (!handler) throw new ApiError(404, "NOT_FOUND", "Not found.");
      return handler(body) as T;
    },
    del: async (path: string) => {
      sent.push({ path, body: null });
      const handler = deletes[path];
      if (!handler) throw new ApiError(404, "NOT_FOUND", "Not found.");
      handler();
    },
  };
  return { api, calls, sent };
}

/** Stands in for the browser WebSocket; tests open it and push messages through it. */
export class FakeSocket implements SocketLike {
  readyState = 0;
  sent: unknown[] = [];
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;
  constructor(readonly url: string) {}
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  push(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

export function fakeSockets() {
  const sockets: FakeSocket[] = [];
  return {
    sockets,
    createSocket: (url: string) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
  };
}

export function renderApp(
  gateway: AuthGateway,
  path = "/",
  api: ApiClient = fakeApi(),
  settings: AppSettings = {},
) {
  return render(
    <AuthProvider gateway={gateway}>
      <ApiContext.Provider value={api}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes {...settings} />
        </MemoryRouter>
      </ApiContext.Provider>
    </AuthProvider>,
  );
}
