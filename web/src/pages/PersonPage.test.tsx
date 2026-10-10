import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import type { Timeline, VisibleEntry } from "../api/people";
import { userFromClaims } from "../auth/user";
import { FakeGateway, REVIEWER, renderApp, routedApi, type Query } from "../test/fakes";

const PATH = "/v1/people/per_1/timeline";

function signedIn() {
  const gateway = new FakeGateway();
  gateway.user = REVIEWER;
  return gateway;
}

function entry(overrides: Partial<VisibleEntry>): VisibleEntry {
  return {
    withheld: false,
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
          withheld: false,
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
  it("links other records a reviewer decided about, without merging them", async () => {
    const { api } = routedApi({
      [PATH]: () =>
        timeline({
          identity: [
            {
              pair_key: "per_1|per_2",
              other_person_id: "per_2",
              decision: "CONFIRMED",
              reviewer: "rev_1",
              decided_at: "2026-10-05T09:02:11Z",
            },
            {
              pair_key: "per_1|per_3",
              other_person_id: "per_3",
              decision: "REJECTED",
              reviewer: "rev_1",
              decided_at: "2026-10-05T09:05:00Z",
            },
          ],
        }),
    });
    renderApp(signedIn(), "/people/per_1", api);
    const section = (await screen.findByRole("heading", { name: "Other records" })).closest(
      "section",
    )!;
    const [confirmed, rejected] = within(section).getAllByRole("listitem");
    expect(confirmed).toHaveTextContent(/Confirmed as the same person as another record/);
    expect(within(confirmed!).getByRole("link")).toHaveAttribute("href", "/people/per_2");
    expect(rejected).toHaveTextContent(/not to be the same person/);
    // The timeline itself is unchanged: only this record's reports are listed.
    expect(screen.getAllByRole("listitem").filter((li) => li.id.startsWith("entry-"))).toHaveLength(2);
  });

  it("has no other records section when nothing was decided", async () => {
    const { api } = routedApi({ [PATH]: () => timeline() });
    renderApp(signedIn(), "/people/per_1", api);
    expect(await screen.findByRole("heading", { name: "Maya Rawat" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Other records" })).toBeNull();
  });

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
    expect(within(hospital).getByText(/Central Hospital Demo/)).toBeInTheDocument();
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

  it("offers publishers a report about this person, and nobody else", async () => {
    localStorage.setItem("found.incidentId", "inc_1");
    const { api } = routedApi({ [PATH]: () => timeline() });
    const publisher = new FakeGateway();
    publisher.user = userFromClaims({ sub: "p", name: "Desk", "cognito:groups": ["publisher"] });
    const view = renderApp(publisher, "/people/per_1", api);
    expect(
      await screen.findByRole("link", { name: "Publish a report about this person" }),
    ).toHaveAttribute("href", "/incidents/inc_1/report?person=per_1&name=Maya+Rawat");
    view.unmount();

    renderApp(signedIn(), "/people/per_1", api);
    await screen.findByRole("heading", { name: "Maya Rawat" });
    expect(screen.queryByRole("link", { name: /Publish a report/ })).not.toBeInTheDocument();
    localStorage.clear();
  });

  it("shows a neutral notice for a sensitive report it may not see", async () => {
    const notice = "A sensitive report was received. A coordinator will contact you.";
    const { api } = routedApi({
      [PATH]: () =>
        timeline({
          summary: {
            label: "Sensitive report received",
            basis: "A coordinator will contact you before the details are shown",
            cited_claim_id: "clm_9",
            conflicts: [{ claim_id: "clm_9", withheld: true, notice }],
            needs_review: false,
          },
          entries: [
            POLICE,
            { claim_id: "clm_9", seq: 2, reported_at: "2026-10-03T02:10:00Z", withheld: true, notice },
          ],
        }),
    });
    renderApp(signedIn(), "/people/per_1", api);
    expect(await screen.findByRole("heading", { name: "Sensitive report received" })).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    const hidden = items.find((li) => li.id === "entry-clm_9")!;
    expect(within(hidden).getByText("Sensitive report")).toBeInTheDocument();
    expect(within(hidden).getByText(notice)).toBeInTheDocument();
    expect(within(hidden).getByText("Used for summary")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "A sensitive report" })).toHaveAttribute("href", "#entry-clm_9");
  });

  it("lets reviewers trace where a report came from", async () => {
    const started = { investigation_id: "inv_7", mode: "LIVE", status: "QUEUED" };
    const { api, sent } = routedApi(
      {
        [PATH]: () => timeline(),
        "/v1/investigations/inv_7": () => {
          throw new ApiError(404, "NOT_FOUND", "Not found.");
        },
      },
      { "/v1/claims/clm_2/investigations": () => started },
    );
    renderApp(signedIn(), "/people/per_1", api);
    const hospital = (await screen.findByText("Admitted, stable condition")).closest("li")!;
    await userEvent.setup().click(
      within(hospital).getByRole("button", { name: "Trace where this came from" }),
    );
    expect(await screen.findByText("This investigation was not found.")).toBeInTheDocument();
    expect(sent).toEqual([{ path: "/v1/claims/clm_2/investigations", body: {} }]);
  });

  it("opens the run already in progress, and explains refusals", async () => {
    let answer: () => unknown = () => {
      throw new ApiError(409, "IN_PROGRESS", "Running.", { investigation_id: "inv_3" });
    };
    const { api, calls } = routedApi(
      {
        [PATH]: () => timeline(),
        "/v1/investigations/inv_3": () => {
          throw new ApiError(404, "NOT_FOUND", "Not found.");
        },
      },
      { "/v1/claims/clm_1/investigations": () => answer() },
    );
    renderApp(signedIn(), "/people/per_1", api);
    const user = userEvent.setup();
    const police = (await screen.findByText("Family reports Maya Rawat missing.")).closest("li")!;
    await user.click(within(police).getByRole("button", { name: "Trace where this came from" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/v1/investigations/inv_3")).toBe(true),
    );

    answer = () => {
      throw new ApiError(503, "LIVE_UNAVAILABLE", "Off.");
    };
    renderApp(signedIn(), "/people/per_1", api);
    const again = (await screen.findAllByText("Family reports Maya Rawat missing."))
      .at(-1)!
      .closest("li")!;
    await user.click(within(again).getByRole("button", { name: "Trace where this came from" }));
    expect(
      await within(again).findByText("Live investigations are switched off right now."),
    ).toBeInTheDocument();
  });

  it("does not offer tracing to publishers", async () => {
    const { api } = routedApi({ [PATH]: () => timeline() });
    const publisher = new FakeGateway();
    publisher.user = userFromClaims({ sub: "p", name: "Desk", "cognito:groups": ["publisher"] });
    renderApp(publisher, "/people/per_1", api);
    await screen.findByRole("heading", { name: "Maya Rawat" });
    expect(screen.queryByRole("button", { name: /Trace where/ })).not.toBeInTheDocument();
  });
});
