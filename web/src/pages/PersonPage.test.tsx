import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Timeline, TimelineEntry } from "../api/people";
import { FakeGateway, REVIEWER, renderApp, routedApi, type Query } from "../test/fakes";

const PATH = "/v1/people/per_1/timeline";

function signedIn() {
  const gateway = new FakeGateway();
  gateway.user = REVIEWER;
  return gateway;
}

function entry(overrides: Partial<TimelineEntry>): TimelineEntry {
  return {
    claim_id: "clm_1",
    seq: 1,
    claim_type: "MISSING",
    value: null,
    source_id: "src_p",
    source: "District Police Demo",
    reported_at: "2026-10-02T15:40:00Z",
    relation: "FIRST",
    excerpt: "Family reports Maya Rawat missing.",
    ...overrides,
  };
}

const POLICE = entry({});
const HOSPITAL = entry({
  claim_id: "clm_2",
  seq: 2,
  claim_type: "FOUND_SAFE",
  source_id: "src_h",
  source: "Central Hospital Demo",
  reported_at: "2026-10-03T02:10:00Z",
  relation: "UPDATE",
  value: "Admitted, stable condition",
  excerpt: "Maya Rawat, 24, admitted to ward 3.",
});
const UNDATED = entry({
  claim_id: "clm_3",
  seq: 3,
  claim_type: "SEEN_AT_LOCATION",
  reported_at: null,
  relation: "NOT_STATUS",
  excerpt: "Seen near the relief camp.",
});

function timeline(overrides: Partial<Timeline> = {}): Timeline {
  return {
    person: { id: "per_1", name: "Maya Rawat", age: 24 },
    summary: {
      label: "Reported found safe",
      basis: "Latest dated status report",
      cited_claim_id: "clm_2",
      conflicts: [
        {
          claim_id: "clm_1",
          claim_type: "MISSING",
          source: "District Police Demo",
        },
      ],
      needs_review: false,
    },
    identity: [],
    entries: [POLICE, HOSPITAL],
    next_cursor: null,
    ...overrides,
  };
}

describe("person page", () => {
  it("shows the cited summary and other sources", async () => {
    const { api } = routedApi({ [PATH]: () => timeline() });
    renderApp(signedIn(), "/people/per_1", api);
    expect(await screen.findByRole("heading", { name: "Maya Rawat" })).toBeInTheDocument();
    const summary = screen.getByRole("heading", { name: "Reported found safe" }).closest("section")!;
    expect(within(summary).getByText(/Latest dated status report/)).toBeInTheDocument();
    expect(
      within(summary).getByRole("link", { name: "See the report this is based on" }),
    ).toHaveAttribute("href", "#entry-clm_2");
    expect(
      within(summary).getByRole("link", { name: "District Police Demo: Missing" }),
    ).toHaveAttribute("href", "#entry-clm_1");
    expect(within(summary).getByText(/does not decide which report is true/)).toBeInTheDocument();
  });

  it("lists every report with source, time, relation and excerpt", async () => {
    const { api } = routedApi({ [PATH]: () => timeline({ entries: [POLICE, HOSPITAL, UNDATED] }) });
    renderApp(signedIn(), "/people/per_1", api);
    const items = await screen.findAllByRole("listitem");
    const hospital = items.find((li) => li.id === "entry-clm_2")!;
    expect(hospital).toHaveClass("cited");
    expect(within(hospital).getByText("Found safe")).toBeInTheDocument();
    expect(within(hospital).getByText("Newer report")).toBeInTheDocument();
    expect(within(hospital).getByText("Used for summary")).toBeInTheDocument();
    expect(within(hospital).getByText("Admitted, stable condition")).toBeInTheDocument();
    expect(within(hospital).getByText(/Central Hospital Demo,/)).toBeInTheDocument();
    const undated = items.find((li) => li.id === "entry-clm_3")!;
    expect(within(undated).getByText(/Reported time unknown/)).toBeInTheDocument();
    expect(within(undated).getByText("Other information", { selector: ".tag" })).toBeInTheDocument();
  });

  it("flags reports waiting for review", async () => {
    const { api } = routedApi({
      [PATH]: () => timeline({ summary: { ...timeline().summary, needs_review: true } }),
    });
    renderApp(signedIn(), "/people/per_1", api);
    expect(await screen.findByRole("note")).toHaveTextContent("waiting for a reviewer");
  });

  it("switches order and pages through the timeline", async () => {
    const { api, calls } = routedApi({
      [PATH]: (q: Query) => {
        if (q.cursor === "next") return timeline({ entries: [POLICE], next_cursor: null });
        return q.order === "desc"
          ? timeline({ entries: [HOSPITAL], next_cursor: "next" })
          : timeline();
      },
    });
    renderApp(signedIn(), "/people/per_1", api);
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Order"), "desc");
    await user.click(await screen.findByRole("button", { name: "Load more" }));
    await screen.findByText("Family reports Maya Rawat missing.");
    expect(calls.at(-1)?.query).toMatchObject({ order: "desc", cursor: "next" });
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("says when the person does not exist", async () => {
    const { api } = routedApi({});
    renderApp(signedIn(), "/people/per_1", api);
    expect(await screen.findByRole("alert")).toHaveTextContent("This person was not found.");
  });

  it("links back to the incident's people", async () => {
    localStorage.setItem("found.incidentId", "inc_1");
    const { api } = routedApi({ [PATH]: () => timeline() });
    renderApp(signedIn(), "/people/per_1", api);
    expect(await screen.findByRole("link", { name: "Back to people" })).toHaveAttribute(
      "href",
      "/incidents/inc_1/people",
    );
    localStorage.clear();
  });

});

