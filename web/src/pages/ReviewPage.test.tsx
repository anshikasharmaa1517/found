import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import type { ReviewItem } from "../api/review";
import { userFromClaims } from "../auth/user";
import { FakeGateway, REVIEWER, fakeSockets, renderApp, routedApi, type Query } from "../test/fakes";

const PATH = "/v1/incidents/inc_1/review-queue";
const WS = "wss://ws.example.org/prod";

function as(user = REVIEWER) {
  const gateway = new FakeGateway();
  gateway.user = user;
  return gateway;
}

function item(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: "rev_held",
    type: "held_alert",
    status: "OPEN",
    priority: 1,
    created_at: "2026-10-05T10:15:00Z",
    ref_id: "clm_9",
    resolved_by: null,
    resolved_at: null,
    note: null,
    person: { id: "per_1", name: "Maya Rawat", age: 24 },
    claim: {
      id: "clm_9",
      claim_type: "DECEASED",
      source: "Central Hospital Demo",
      reported_at: "2026-10-03T02:10:00Z",
      excerpt: "Hospital record of death for Maya Rawat.",
    },
    investigation: null,
    ...overrides,
  };
}

const CONFLICT = item({
  id: "rev_conflict",
  type: "conflict",
  priority: 2,
  claim: {
    id: "clm_2",
    claim_type: "FOUND_SAFE",
    source: "Flood Relief Demo",
    reported_at: null,
    excerpt: "Maya Rawat is safe.",
  },
});
const FINDING = item({
  id: "rev_finding",
  type: "finding",
  priority: 3,
  claim: {
    id: "clm_relay",
    claim_type: "FOUND_SAFE",
    source: "Flood Relief Demo",
    reported_at: null,
    excerpt: "According to Central Hospital Demo, Maya Rawat was admitted.",
  },
  investigation: {
    id: "inv_1",
    status: "NEEDS_REVIEW",
    attribution: "RELAY",
    comparison: "SUPPORTS",
    outcome_reasons: ["RELAY_NOT_FIRST_HAND"],
  },
});

afterEach(() => localStorage.clear());

describe("review queue", () => {
  it("lists items with their context and filters by type", async () => {
    const { api, calls } = routedApi({
      [PATH]: (q: Query) => ({
        items: q.type === "conflict" ? [CONFLICT] : [item(), CONFLICT, FINDING],
        next_cursor: null,
      }),
    });
    renderApp(as(), "/incidents/inc_1/review", api);
    expect(await screen.findByText("Sensitive report held")).toBeInTheDocument();
    expect(screen.getByText("Hospital record of death for Maya Rawat.")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Maya Rawat" })[0]).toHaveAttribute("href", "/people/per_1");
    expect(screen.getByRole("link", { name: "Open the investigation" })).toHaveAttribute(
      "href",
      "/investigations/inv_1",
    );
    expect(screen.getByText(/A relay is not independent confirmation/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Release report" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark resolved" })).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "Conflicts" }));
    await waitFor(() => expect(screen.queryByText("Sensitive report held")).not.toBeInTheDocument());
    expect(calls.at(-1)).toEqual({ path: PATH, query: { type: "conflict", status: "OPEN" } });
  });

  it("releases a held report with a note and reloads", async () => {
    let open = true;
    const { api, sent } = routedApi(
      { [PATH]: () => ({ items: open ? [item()] : [], next_cursor: null }) },
      {
        "/v1/incidents/inc_1/review-items/rev_held/resolve": () => {
          open = false;
          return { id: "rev_held", status: "DONE", resolved_by: "u1", alerts_released: 2 };
        },
      },
    );
    renderApp(as(), "/incidents/inc_1/review", api);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Note (optional)"), "Family told by phone.");
    await user.click(screen.getByRole("button", { name: "Release report" }));
    expect(await screen.findByText("Nothing waits for review.")).toBeInTheDocument();
    expect(sent).toEqual([
      {
        path: "/v1/incidents/inc_1/review-items/rev_held/resolve",
        body: { note: "Family told by phone." },
      },
    ]);
  });

  it("says when another reviewer got there first", async () => {
    const { api } = routedApi(
      { [PATH]: () => ({ items: [CONFLICT], next_cursor: null }) },
      {
        "/v1/incidents/inc_1/review-items/rev_conflict/resolve": () => {
          throw new ApiError(409, "VERSION_CONFLICT", "Done already.");
        },
      },
    );
    renderApp(as(), "/incidents/inc_1/review", api);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Mark resolved" }));
    expect(await screen.findByText("Another reviewer already resolved this item.")).toBeInTheDocument();
  });

  it("shows resolved items with their note", async () => {
    const done = item({ status: "DONE", resolved_at: "2026-10-05T11:00:00Z", note: "Family told." });
    const { api } = routedApi({ [PATH]: (q: Query) => ({ items: q.status === "DONE" ? [done] : [], next_cursor: null }) });
    renderApp(as(), "/incidents/inc_1/review?status=DONE", api);
    expect(await screen.findByText(/Family told\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Release report" })).not.toBeInTheDocument();
  });

  it("reloads when a new review item arrives live", async () => {
    let items: ReviewItem[] = [];
    const { api } = routedApi({ [PATH]: () => ({ items, next_cursor: null }) });
    const { sockets, createSocket } = fakeSockets();
    localStorage.setItem("found.incidentId", "inc_1");
    renderApp(as(), "/incidents/inc_1/review", api, { wsUrl: WS, createSocket });
    expect(await screen.findByText("Nothing waits for review.")).toBeInTheDocument();
    await waitFor(() => expect(sockets).toHaveLength(1));
    act(() => sockets[0]!.open());
    items = [CONFLICT];
    act(() =>
      sockets[0]!.push({
        type: "review.created",
        incident_id: "inc_1",
        review_id: "rev_conflict",
        item_type: "conflict",
      }),
    );
    expect(await screen.findByText("Reports disagree")).toBeInTheDocument();
  });

  it("is linked for reviewers and closed to other roles", async () => {
    localStorage.setItem("found.incidentId", "inc_1");
    const { api } = routedApi({
      [PATH]: () => ({ items: [], next_cursor: null }),
      "/v1/health": () => ({ status: "ok" }),
    });
    const view = renderApp(as(), "/", api);
    expect(await screen.findByRole("link", { name: "Review" })).toHaveAttribute(
      "href",
      "/incidents/inc_1/review",
    );
    view.unmount();
    const publisher = userFromClaims({ sub: "p", name: "Desk", "cognito:groups": ["publisher"] });
    renderApp(as(publisher), "/incidents/inc_1/review", api);
    expect(await screen.findByText("Not available for your role")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation")).queryByRole("link", { name: "Review" })).toBeNull();
  });
});
