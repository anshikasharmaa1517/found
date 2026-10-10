import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { FakeGateway, REVIEWER, renderApp, routedApi, type Query } from "../test/fakes";

const PATH = "/v1/incidents/inc_1/people";

function signedIn() {
  const gateway = new FakeGateway();
  gateway.user = REVIEWER;
  return gateway;
}

const MAYA = { id: "per_1", name: "Maya Rawat", age: 24 };
const MOHAN = { id: "per_2", name: "Mohan Rawat", age: null };
const RAVI = { id: "per_3", name: "Ravi Kumar", age: 30 };

afterEach(() => localStorage.clear());

describe("people page", () => {
  it("lists people with links and remembers the incident", async () => {
    const { api } = routedApi({ [PATH]: () => ({ people: [MAYA, MOHAN], next_cursor: null }) });
    renderApp(signedIn(), "/incidents/inc_1/people", api);
    const link = await screen.findByRole("link", { name: "Maya Rawat" });
    expect(link).toHaveAttribute("href", "/people/per_1");
    expect(screen.getByText("Not reported")).toBeInTheDocument();
    expect(localStorage.getItem("found.incidentId")).toBe("inc_1");
    expect(screen.getByRole("link", { name: "People" })).toBeInTheDocument();
  });

  it("searches by name and age through the URL", async () => {
    const { api, calls } = routedApi({
      [PATH]: (q: Query) =>
        q.q ? { people: [MAYA], next_cursor: null } : { people: [MAYA, RAVI], next_cursor: null },
    });
    renderApp(signedIn(), "/incidents/inc_1/people", api);
    await screen.findByRole("link", { name: "Ravi Kumar" });
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Name"), "rawat");
    await user.type(screen.getByLabelText("Age"), "25");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText(/Ages match within 2 years/);
    expect(screen.queryByRole("link", { name: "Ravi Kumar" })).not.toBeInTheDocument();
    expect(calls.at(-1)?.query).toMatchObject({ q: "rawat", age: "25" });
  });

  it("loads more pages with the cursor", async () => {
    const { api, calls } = routedApi({
      [PATH]: (q: Query) =>
        q.cursor === "c2"
          ? { people: [RAVI], next_cursor: null }
          : { people: [MAYA, MOHAN], next_cursor: "c2" },
    });
    renderApp(signedIn(), "/incidents/inc_1/people", api);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Load more" }));
    const list = await screen.findByRole("table");
    await within(list).findByRole("link", { name: "Ravi Kumar" });
    expect(within(list).getAllByRole("row")).toHaveLength(4); // header and three people
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(calls.at(-1)?.query.cursor).toBe("c2");
  });

  it("says when nothing matches", async () => {
    const { api } = routedApi({ [PATH]: () => ({ people: [], next_cursor: null }) });
    renderApp(signedIn(), "/incidents/inc_1/people?q=zed", api);
    expect(await screen.findByText("No people match this search.")).toBeInTheDocument();
  });

  it("explains an unknown incident", async () => {
    const { api } = routedApi({});
    renderApp(signedIn(), "/incidents/inc_x/people", api);
    expect(await screen.findByRole("alert")).toHaveTextContent("This incident does not exist.");
  });

  it("opens an incident from the home page", async () => {
    const { api } = routedApi({
      "/v1/health": () => ({ status: "ok" }),
      [PATH]: () => ({ people: [MAYA], next_cursor: null }),
    });
    renderApp(signedIn(), "/", api);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Incident"), "inc_1");
    await user.click(screen.getByRole("button", { name: "Open people" }));
    expect(await screen.findByRole("link", { name: "Maya Rawat" })).toBeInTheDocument();
  });

  it("rejects an incident id that is not id-shaped", async () => {
    const { api } = routedApi({ "/v1/health": () => ({ status: "ok" }) });
    renderApp(signedIn(), "/", api);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Incident"), "../admin");
    await user.click(screen.getByRole("button", { name: "Open people" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter an incident id");
  });
});

const STATUSED = {
  ...MAYA,
  status: {
    label: "Reported found safe",
    claim_type: "FOUND_SAFE",
    needs_review: false,
    conflicts: 1,
    report_count: 3,
    withheld: false,
  },
};

function overviewRoutes() {
  return routedApi({
    [PATH]: () => ({ people: [STATUSED, RAVI], next_cursor: null }),
    [`${PATH}/stats`]: () => ({
      people: 2,
      by_status: { MISSING: 1, FOUND_SAFE: 1 },
      disagree: 1,
      needs_review: 0,
      matches_open: 1,
      matches_decided: 0,
    }),
    "/v1/incidents/inc_1/review-queue": () => ({
      items: [
        {
          id: "rev_i",
          type: "identity",
          status: "OPEN",
          priority: 3,
          created_at: "2026-10-05T10:15:00Z",
          ref_id: "per_1|per_9",
          resolved_by: null,
          resolved_at: null,
          note: null,
          person: null,
          claim: null,
          investigation: null,
          proposal: {
            pair_key: "per_1|per_9",
            people: [
              { id: "per_1", name: "Maya Rawat", age: 24, incident_id: "inc_1" },
              { id: "per_9", name: "Maya R.", age: 24, incident_id: "inc_1" },
            ],
            reasons: ["GIVEN_EXACT", "AGE_EQUAL"],
            score: 40,
            proposed_by: "resolver",
          },
        },
      ],
      next_cursor: null,
    }),
    "/v1/people/per_1/timeline": () => ({
      person: MAYA,
      summary: {
        label: "Reported found safe",
        basis: "Latest dated status report",
        cited_claim_id: "clm_2",
        conflicts: [
          { claim_id: "clm_1", claim_type: "MISSING", source: "District Police Demo", withheld: false },
        ],
        needs_review: false,
      },
      identity: [],
      entries: [
        {
          withheld: false,
          claim_id: "clm_2",
          seq: 2,
          claim_type: "FOUND_SAFE",
          value: null,
          source_id: "src_h",
          source: "Central Hospital Demo",
          reported_at: "2026-10-03T02:10:00Z",
          relation: "UPDATE",
          excerpt: "Maya Rawat, 24, admitted to ward 3.",
        },
      ],
      next_cursor: null,
    }),
  });
}

function wide(matches: boolean) {
  window.matchMedia = ((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

describe("people overview", () => {
  it("shows counts, statuses and possible matches", async () => {
    const { api } = overviewRoutes();
    renderApp(signedIn(), "/incidents/inc_1/people", api);
    const stats = await screen.findByLabelText("2 people reported");
    expect(within(stats).getByText("Latest report: missing")).toBeInTheDocument();
    expect(within(stats).getByText("Possible matches to review")).toBeInTheDocument();
    const row = await screen.findByRole("row", { name: /Maya Rawat/ });
    expect(within(row).getByText("Reported found safe")).toBeInTheDocument();
    expect(within(row).getByText("3")).toBeInTheDocument();
    const matches = (await screen.findByRole("heading", { name: "Could these be the same person?" })).closest(
      "section",
    )!;
    expect(within(matches).getByText(/Same given name, Same age/)).toBeInTheDocument();
    expect(within(matches).getByRole("link", { name: "Review matches" })).toHaveAttribute(
      "href",
      "/incidents/inc_1/review?type=identity",
    );
  });

  it("previews a person beside the list on wide screens", async () => {
    wide(true);
    const { api } = overviewRoutes();
    renderApp(signedIn(), "/incidents/inc_1/people", api);
    expect(await screen.findByText("Pick someone to see what is known")).toBeInTheDocument();
    const table = await screen.findByRole("table");
    await userEvent.setup().click(within(table).getByRole("link", { name: "Maya Rawat" }));
    const preview = (await screen.findByRole("heading", { name: "Maya Rawat", level: 2 })).closest(
      "section",
    )!;
    expect(within(preview).getByText(/District Police Demo, Missing/)).toBeInTheDocument();
    expect(within(preview).getByText("Maya Rawat, 24, admitted to ward 3.")).toBeInTheDocument();
    expect(within(preview).getByRole("link", { name: "Open the full timeline" })).toHaveAttribute(
      "href",
      "/people/per_1",
    );
    // Still on the list.
    expect(screen.getByRole("heading", { name: "People", level: 1 })).toBeInTheDocument();
  });

  it("opens the full page on small screens", async () => {
    wide(false);
    const { api } = overviewRoutes();
    renderApp(signedIn(), "/incidents/inc_1/people", api);
    const table = await screen.findByRole("table");
    await userEvent.setup().click(within(table).getByRole("link", { name: "Maya Rawat" }));
    expect(await screen.findByRole("heading", { name: "Maya Rawat", level: 1 })).toBeInTheDocument();
  });
});
