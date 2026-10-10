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

const PAIR = "per_1|per_2";
const IDENTITY = item({
  id: "rev_identity",
  type: "identity",
  priority: 3,
  ref_id: PAIR,
  person: { id: "per_2", name: "Maya R.", age: 24 },
  claim: null,
  proposal: {
    pair_key: PAIR,
    people: [
      { id: "per_1", name: "Maya Rawat", age: 24, incident_id: "inc_1" },
      { id: "per_2", name: "Maya R.", age: 24, incident_id: "inc_1" },
    ],
    reasons: ["GIVEN_EXACT", "AGE_EQUAL", "SHARED_LOCATION"],
    score: 55,
    proposed_by: "resolver",
  },
});
const DECISION_PATH = "/v1/identity-proposals/per_1%7Cper_2/decision";

function timelineOf(id: string, name: string, excerpt: string) {
  return () => ({
    person: { id, name, age: 24 },
    summary: { label: "Reported missing", basis: "", cited_claim_id: null, conflicts: [], needs_review: false },
    identity: [],
    entries: [
      {
        withheld: false,
        claim_id: `clm_${id}`,
        seq: 1,
        claim_type: "MISSING",
        value: null,
        source_id: "src_p",
        source: "District Police Demo",
        reported_at: "2026-10-02T15:40:00Z",
        relation: "FIRST",
        excerpt,
      },
    ],
    next_cursor: null,
  });
}

describe("identity review", () => {
  it("explains the proposal and compares both records side by side", async () => {
    const { api, calls } = routedApi({
      [PATH]: () => ({ items: [IDENTITY], next_cursor: null }),
      "/v1/people/per_1/timeline": timelineOf("per_1", "Maya Rawat", "Maya Rawat missing near the bridge."),
      "/v1/people/per_2/timeline": timelineOf("per_2", "Maya R.", "Maya R. seen at the Old Bridge."),
    });
    renderApp(as(), "/incidents/inc_1/review", api);
    expect(await screen.findByText("Possible same person", { selector: "strong" })).toBeInTheDocument();
    const reasons = screen.getByRole("list", { name: "Why this pair was proposed" });
    expect(within(reasons).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Same given name",
      "Same age",
      "Reported at the same place",
    ]);
    expect(screen.getByText(/Records are never merged/)).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "Compare their reports" }));
    expect(await screen.findByText("Maya Rawat missing near the bridge.")).toBeInTheDocument();
    expect(screen.getByText("Maya R. seen at the Old Bridge.")).toBeInTheDocument();
    expect(calls.filter((c) => c.path.endsWith("/timeline")).map((c) => c.query)).toEqual([
      { limit: 20 },
      { limit: 20 },
    ]);
  });

  it("needs a note, then records the decision and reloads", async () => {
    let open = true;
    const { api, sent } = routedApi(
      { [PATH]: () => ({ items: open ? [IDENTITY] : [], next_cursor: null }) },
      {
        [DECISION_PATH]: () => {
          open = false;
          return { decision: { pair_key: PAIR, decision: "CONFIRMED", version: 1 } };
        },
      },
    );
    renderApp(as(), "/incidents/inc_1/review", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Same person" }));
    expect(screen.getByText("Say what you checked before deciding.")).toBeInTheDocument();
    expect(sent).toEqual([]);

    await user.type(screen.getByLabelText("Note (required)"), "Same age, same bridge.");
    await user.click(screen.getByRole("button", { name: "Same person" }));
    expect(await screen.findByText("Nothing waits for review.")).toBeInTheDocument();
    expect(sent).toEqual([
      {
        path: DECISION_PATH,
        body: { decision: "CONFIRMED", note: "Same age, same bridge.", expected_version: 0 },
      },
    ]);
  });

  it("rejects a pair and says when another reviewer decided first", async () => {
    const { api, sent } = routedApi(
      { [PATH]: () => ({ items: [IDENTITY], next_cursor: null }) },
      {
        [DECISION_PATH]: () => {
          throw new ApiError(409, "VERSION_CONFLICT", "Decided meanwhile.");
        },
      },
    );
    renderApp(as(), "/incidents/inc_1/review", api);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Note (required)"), "Different mothers named.");
    await user.click(screen.getByRole("button", { name: "Not the same person" }));
    expect(await screen.findByText(/Another reviewer decided this pair meanwhile/)).toBeInTheDocument();
    expect(sent[0]!.body).toMatchObject({ decision: "REJECTED" });
  });

  it("shows decided pairs without the decision buttons and filters by type", async () => {
    const done = { ...IDENTITY, status: "DONE" as const, resolved_at: "2026-10-05T11:00:00Z", note: "Same bridge." };
    const { api, calls } = routedApi({
      [PATH]: (q: Query) => ({ items: q.status === "DONE" ? [done] : [], next_cursor: null }),
    });
    renderApp(as(), "/incidents/inc_1/review?status=DONE", api);
    expect(await screen.findByText(/Same bridge\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Same person" })).toBeNull();
    await userEvent.setup().click(screen.getByRole("button", { name: "Possible same person" }));
    await waitFor(() =>
      expect(calls.at(-1)).toEqual({ path: PATH, query: { type: "identity", status: "DONE" } }),
    );
  });
});
