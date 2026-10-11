import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import type { RecentReport } from "../api/incidents";
import type { SourceSummary } from "../api/sources";
import { userFromClaims } from "../auth/user";
import { FakeGateway, REVIEWER, renderApp, routedApi } from "../test/fakes";

const BASE = "/v1/incidents/inc_1";
const PUBLISHER = userFromClaims({
  sub: "p",
  "cognito:groups": ["publisher"],
  "custom:org_id": "org_h",
});

function source(overrides: Partial<SourceSummary> = {}): SourceSummary {
  return {
    id: "src_h",
    name: "Central Hospital Demo",
    source_type: "HOSPITAL",
    organization_id: "org_h",
    reports: 3,
    by_type: { OTHER: 1, FOUND_SAFE: 1, MISSING: 1 },
    cited_by: 2,
    latest_at: "2026-10-05T10:15:00Z",
    ...overrides,
  };
}

const RELIEF = source({
  id: "src_n",
  name: "Flood Relief Demo",
  source_type: "NGO",
  organization_id: "org_n",
  reports: 1,
  by_type: { WITHHELD: 1 },
  cited_by: 0,
});

const REPORTS: RecentReport[] = [
  {
    claim_id: "clm_2",
    subject_id: "per_1",
    subject_type: "PERSON",
    subject_name: "Maya Rawat",
    ingested_at: "2026-10-05T10:10:00Z",
    withheld: false,
    claim_type: "FOUND_SAFE",
    source: "Central Hospital Demo",
    reported_at: "2026-10-03T02:10:00Z",
    excerpt: "Maya Rawat, 24, admitted to ward 3.",
  },
  {
    claim_id: "clm_5",
    subject_id: "inf_1",
    subject_type: "INFRASTRUCTURE",
    subject_name: "Old Bridge",
    ingested_at: "2026-10-05T10:00:00Z",
    withheld: false,
    claim_type: "BRIDGE_DAMAGED",
    source: "Central Hospital Demo",
    reported_at: null,
    excerpt: "Ambulances cannot cross the Old Bridge.",
  },
];

function as(user = REVIEWER) {
  const gateway = new FakeGateway();
  gateway.user = user;
  return gateway;
}

function routes(sources: SourceSummary[] = [source(), RELIEF]) {
  return routedApi({
    [`${BASE}/sources`]: () => ({ sources }),
    [`${BASE}/recent`]: () => ({ reports: REPORTS }),
  });
}

afterEach(() => localStorage.clear());

describe("sources page", () => {
  it("shows each source with its counts, the types it reported and who relays it", async () => {
    const { api } = routes();
    renderApp(as(), "/incidents/inc_1/sources", api);
    const card = (await screen.findByRole("heading", { name: "Central Hospital Demo" })).closest(
      "article",
    )!;
    expect(within(card).getByText("Hospital")).toBeInTheDocument();
    expect(within(card).getByText("3")).toBeInTheDocument();
    const types = within(within(card).getByRole("list", { name: "Reports by type" }))
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    // Status types first, in a fixed order.
    expect(types).toEqual(["Missing 1", "Found safe 1", "Other information 1"]);
    expect(within(card).getByText(/Named by 2 reports from other sources/)).toBeInTheDocument();
    expect(within(card).getByText(/not independent confirmation/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sources" })).toHaveAttribute("aria-current", "page");

    const relief = screen.getByRole("heading", { name: "Flood Relief Demo" }).closest("article")!;
    expect(within(relief).getByRole("listitem")).toHaveTextContent("Held for review 1");
    expect(within(relief).getByText("No other source names this one.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Publish a report/ })).toBeNull();
  });

  it("opens a source's own reports on request", async () => {
    const { api, calls } = routes();
    renderApp(as(), "/incidents/inc_1/sources", api);
    const card = (await screen.findByRole("heading", { name: "Central Hospital Demo" })).closest(
      "article",
    )!;
    const toggle = within(card).getByRole("button", { name: "Show reports" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.setup().click(toggle);
    expect(await within(card).findByRole("link", { name: "Maya Rawat" })).toHaveAttribute(
      "href",
      "/people/per_1",
    );
    expect(within(card).getByText("Maya Rawat, 24, admitted to ward 3.")).toBeInTheDocument();
    // Roads and shelters are not people, so they are named, not linked.
    expect(within(card).getByText("Old Bridge")).not.toHaveAttribute("href");
    expect(within(card).getByRole("button", { name: "Hide reports" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    // The rail asks for the whole incident; the card asks for its source only.
    expect(calls.filter((c) => c.path === `${BASE}/recent`).map((c) => c.query)).toContainEqual({
      limit: 20,
      source_id: "src_h",
    });
  });

  it("filters by name and explains an empty result", async () => {
    const { api } = routes();
    renderApp(as(), "/incidents/inc_1/sources", api);
    await screen.findByRole("heading", { name: "Central Hospital Demo" });
    const user = userEvent.setup();
    await user.type(screen.getByRole("searchbox", { name: /Search sources/ }), "relief");
    expect(screen.queryByRole("heading", { name: "Central Hospital Demo" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Flood Relief Demo" })).toBeInTheDocument();
    expect(screen.getByText("1 of 2 sources shown")).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: /Search sources/ }), "zzz");
    expect(screen.getByText("No sources match this search.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByText("2 of 2 sources shown")).toBeInTheDocument();
  });

  it("offers publishers the report form and says when nobody has published", async () => {
    const { api } = routes([]);
    renderApp(as(PUBLISHER), "/incidents/inc_1/sources", api);
    expect(await screen.findByText("No sources yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Publish a report" })).toHaveAttribute(
      "href",
      "/incidents/inc_1/report",
    );
  });

  it("explains an unknown incident", async () => {
    renderApp(as(), "/incidents/inc_x/sources", routedApi({}).api);
    expect(await screen.findByText("This incident does not exist.")).toBeInTheDocument();
  });
});
