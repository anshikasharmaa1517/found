import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import type { Alert } from "../api/alerts";
import { userFromClaims } from "../auth/user";
import { FakeGateway, REVIEWER, fakeSockets, renderApp, routedApi, type Call } from "../test/fakes";

const FAMILY = userFromClaims({ sub: "fam_1", name: "Asha", "cognito:groups": ["family"] });
const WS = "wss://ws.example.org/prod";

function as(user = FAMILY) {
  const gateway = new FakeGateway();
  gateway.user = user;
  return gateway;
}

function alert(n: number, overrides: Partial<Alert> = {}): Alert {
  return {
    id: `alr_${n}`,
    incident_id: "inc_1",
    person_id: "per_1",
    claim_id: `clm_${n}`,
    relation: "UPDATE",
    severity: "info",
    message: `Newer report ${n} for Maya Rawat.`,
    delivery_status: "NOT_REQUIRED",
    created_at: "2026-10-05T10:15:00Z",
    ...overrides,
  };
}

const ALERT_MESSAGE = {
  type: "alert.created",
  alert_id: "alr_9",
  subject_id: "per_1",
  severity: "info",
  message: "Newer report for Maya Rawat: Central Hospital Demo says found safe.",
};

function count(calls: Call[], path: string) {
  return calls.filter((c) => c.path === path).length;
}

afterEach(() => localStorage.clear());

describe("live alerts", () => {
  it("connects with the token, shows the status and toasts a new alert", async () => {
    const { sockets, createSocket } = fakeSockets();
    renderApp(as(), "/", routedApi({ "/v1/health": () => ({ status: "ok" }) }).api, {
      wsUrl: WS,
      createSocket,
    });
    await waitFor(() => expect(sockets).toHaveLength(1));
    expect(sockets[0]!.url).toBe(`${WS}?token=token`);
    act(() => sockets[0]!.open());
    expect(await screen.findByText("Live")).toBeInTheDocument();
    // Family accounts only get their own alerts, so they never subscribe to an incident.
    expect(sockets[0]!.sent).toEqual([]);

    act(() => sockets[0]!.push(ALERT_MESSAGE));
    const toast = (await screen.findByText(ALERT_MESSAGE.message)).closest(".toast") as HTMLElement;
    expect(within(toast).getByRole("link", { name: "View timeline" })).toHaveAttribute(
      "href",
      "/people/per_1",
    );
    expect(screen.getByRole("link", { name: "Alerts, 1 new" })).toBeInTheDocument();

    await userEvent.setup().click(within(toast).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(ALERT_MESSAGE.message)).not.toBeInTheDocument();
  });

  it("staff follow the open incident and reviewers hear about new review items", async () => {
    const { sockets, createSocket } = fakeSockets();
    const { api } = routedApi({
      "/v1/incidents/inc_1/people": () => ({ people: [], next_cursor: null }),
    });
    renderApp(as(REVIEWER), "/incidents/inc_1/people", api, { wsUrl: WS, createSocket });
    await waitFor(() => expect(sockets).toHaveLength(1));
    act(() => sockets[0]!.open());
    expect(sockets[0]!.sent).toEqual([{ action: "subscribe", incident_id: "inc_1" }]);

    act(() =>
      sockets[0]!.push({ type: "review.created", incident_id: "inc_1", review_id: "rev_1", item_type: "conflict" }),
    );
    expect(await screen.findByText("A new item is waiting for review.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Alerts/ })).not.toBeInTheDocument();
  });

  it("refreshes the open timeline when a report about that person arrives", async () => {
    const { sockets, createSocket } = fakeSockets();
    const path = "/v1/people/per_1/timeline";
    const timeline = {
      person: { id: "per_1", name: "Maya Rawat", age: 24 },
      summary: { label: "Reported missing", basis: "b", cited_claim_id: null, conflicts: [], needs_review: false },
      identity: [],
      entries: [],
      next_cursor: null,
    };
    const { api, calls } = routedApi({ [path]: () => timeline });
    renderApp(as(REVIEWER), "/people/per_1", api, { wsUrl: WS, createSocket });
    await screen.findByRole("heading", { name: "Maya Rawat" });
    await waitFor(() => expect(sockets).toHaveLength(1));
    act(() => sockets[0]!.open());
    const before = count(calls, path);

    act(() => sockets[0]!.push({ type: "claim.created", incident_id: "inc_1", claim_id: "c", subject_id: "per_2", at: "x" }));
    act(() => sockets[0]!.push({ type: "claim.created", incident_id: "inc_1", claim_id: "c", subject_id: "per_1", at: "x" }));
    await waitFor(() => expect(count(calls, path)).toBe(before + 1));
    expect(screen.getByRole("heading", { name: "Maya Rawat" })).toBeInTheDocument();
  });

  it("works without live updates when no WebSocket URL is set", async () => {
    renderApp(as(), "/", routedApi({ "/v1/health": () => ({ status: "ok" }) }).api);
    expect(await screen.findByRole("heading", { name: "Welcome, Asha" })).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });
});

describe("alerts page", () => {
  it("lists alerts with how they were delivered, and refetches on a new one", async () => {
    const { sockets, createSocket } = fakeSockets();
    let page = [alert(1, { severity: "high", delivery_status: "HELD" }), alert(2, { delivery_status: "SENT" })];
    const { api, calls } = routedApi({ "/v1/me/alerts": () => ({ alerts: page, next_cursor: null }) });
    renderApp(as(), "/alerts", api, { wsUrl: WS, createSocket });
    expect(await screen.findByText("Newer report 1 for Maya Rawat.")).toBeInTheDocument();
    expect(screen.getByText(/A coordinator will contact you/)).toBeInTheDocument();
    expect(screen.getByText(/Also sent by text or email/)).toBeInTheDocument();

    await waitFor(() => expect(sockets).toHaveLength(1));
    act(() => sockets[0]!.open());
    page = [alert(3), ...page];
    act(() => sockets[0]!.push(ALERT_MESSAGE));
    expect(await screen.findByText("Newer report 3 for Maya Rawat.")).toBeInTheDocument();
    expect(count(calls, "/v1/me/alerts")).toBe(2);
    // Already on the alerts page, so nothing counts as unread.
    expect(screen.getByRole("link", { name: "Alerts" })).toBeInTheDocument();
  });

  it("pages and explains an empty feed", async () => {
    const { api } = routedApi({
      "/v1/me/alerts": (q) =>
        q.cursor === "c2"
          ? { alerts: [alert(3)], next_cursor: null }
          : { alerts: [alert(1), alert(2)], next_cursor: "c2" },
    });
    renderApp(as(), "/alerts", api);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Newer report 3 for Maya Rawat.")).toBeInTheDocument();

    const empty = routedApi({ "/v1/me/alerts": () => ({ alerts: [], next_cursor: null }) });
    renderApp(as(), "/alerts", empty.api);
    expect(await screen.findByText(/No alerts yet/)).toBeInTheDocument();
  });

  it("is only for family accounts", async () => {
    renderApp(as(REVIEWER), "/alerts", routedApi({}).api);
    expect(await screen.findByRole("heading", { name: "Not available for your role" })).toBeInTheDocument();
  });
});
