import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RecentReport } from "../api/incidents";
import { userFromClaims } from "../auth/user";
import { FakeGateway, REVIEWER, renderApp, routedApi } from "../test/fakes";

vi.mock("../components/PlacesMap", () => ({
  default: () => <div data-testid="map">map</div>,
}));

const BASE = "/v1/incidents/inc_demo";
const INCIDENT = {
  id: "inc_demo",
  name: "Kesari Valley flood (fictional demo)",
  area: "Kesari valley, Uttarakhand (fictional)",
  is_demo: true,
  started_at: "2026-10-02T13:00:00Z",
};
const RECENT: RecentReport[] = [
  {
    claim_id: "clm_9",
    subject_id: "per_9",
    subject_type: "PERSON",
    subject_name: "Ramesh Thapliyal",
    ingested_at: "2026-10-05T10:15:00Z",
    withheld: true,
    notice: "A sensitive report was received. A coordinator will contact you.",
  },
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
];

function routes(overrides: Record<string, () => unknown> = {}) {
  return routedApi({
    [BASE]: () => INCIDENT,
    [`${BASE}/recent`]: () => ({ reports: RECENT }),
    [`${BASE}/map`]: () => ({
      places: [],
      located_reports: 0,
      unlocated_reports: 0,
      caveat: "",
      updated_at: "2026-10-05T10:15:00Z",
    }),
    [`${BASE}/climate`]: () => ({ features: [], caveat: "", updated_at: "2026-10-05T10:15:00Z" }),
    [`${BASE}/people`]: () => ({
      people: [
        { id: "per_1", name: "Maya Rawat", age: 24 },
        { id: "per_2", name: "Maya R.", age: 24 },
      ],
      next_cursor: null,
    }),
    "/v1/people/per_1/timeline": () => ({
      person: { id: "per_1", name: "Maya Rawat", age: 24 },
      summary: { label: "", basis: "", cited_claim_id: null, conflicts: [], needs_review: false },
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
          reported_at: null,
          relation: "UPDATE",
          excerpt: "Maya Rawat admitted.",
        },
        {
          withheld: false,
          claim_id: "clm_3",
          seq: 3,
          claim_type: "FOUND_SAFE",
          value: null,
          source_id: "src_n",
          source: "Flood Relief Demo",
          reported_at: null,
          relation: "UPDATE",
          excerpt: "According to Central Hospital Demo, Maya is safe.",
        },
      ],
      next_cursor: null,
    }),
    [`${BASE}/graph`]: () => ({
      nodes: [
        { id: "per_1", kind: "person", label: "Maya Rawat", detail: "Age 24", subject_type: "PERSON" },
        { id: "per_2", kind: "person", label: "Maya R.", detail: "Age 24", subject_type: "PERSON" },
        { id: "clm_2", kind: "report", label: "Found safe", detail: "Central Hospital Demo", subject_type: null },
        { id: "src_h", kind: "source", label: "Central Hospital Demo", detail: null, subject_type: null },
        { id: "per_3", kind: "person", label: "Arjun Negi", detail: null, subject_type: "PERSON" },
      ],
      edges: [
        { source: "clm_2", target: "per_1", kind: "about" },
        { source: "clm_2", target: "src_h", kind: "from" },
        { source: "per_1", target: "per_2", kind: "possibly_same" },
      ],
      by_kind: { person: 3, report: 1, source: 1 },
    }),
    ...overrides,
  });
}

function as(user = REVIEWER) {
  const gateway = new FakeGateway();
  gateway.user = user;
  return gateway;
}

afterEach(() => localStorage.clear());

describe("incident overview", () => {
  it("names the incident and walks through the demo story", async () => {
    const { api } = routes();
    renderApp(as(), "/incidents/inc_demo", api, { mapStyleUrl: "https://tiles.example/style" });
    expect(
      await screen.findByRole("heading", { name: "Kesari Valley flood (fictional demo)" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Kesari valley, Uttarakhand/)).toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "Maya is reported missing" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See every report about Maya" })).toHaveAttribute(
      "href",
      "/people/per_1",
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Next step" }));
    expect(screen.getByRole("link", { name: "Review the possible match" })).toHaveAttribute(
      "href",
      "/incidents/inc_demo/review?type=identity",
    );
    await user.click(screen.getByRole("button", { name: /Hospital says safe/ }));
    expect(screen.getByRole("link", { name: "See the hospital report" })).toHaveAttribute(
      "href",
      "/people/per_1#entry-clm_2",
    );
    await user.click(screen.getByRole("button", { name: /Where did it come from/ }));
    // Reviewers start the trace from the story itself.
    expect(screen.getByRole("button", { name: "Trace where this came from" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next step" })).toBeNull();
  });

  it("gives families the other record instead of the review queue", async () => {
    const family = userFromClaims({ sub: "f", name: "Asha", "cognito:groups": ["family"] });
    const { api } = routes({ "/v1/me/alerts": () => ({ alerts: [], next_cursor: null }) });
    renderApp(as(family), "/incidents/inc_demo", api);
    await screen.findByRole("heading", { name: "Maya is reported missing" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Next step" }));
    expect(screen.getByRole("link", { name: "See the other record" })).toHaveAttribute(
      "href",
      "/people/per_2",
    );
    expect(await screen.findByText(/Follow a person from their page/)).toBeInTheDocument();
  });

  it("shows recent updates with sensitive reports masked, and the people tab", async () => {
    const { api } = routes();
    renderApp(as(), "/incidents/inc_demo", api, { mapStyleUrl: "https://tiles.example/style" });
    const recent = (await screen.findByRole("heading", { name: "Recent updates" })).closest(
      "section",
    )!;
    expect(await within(recent).findByText("Sensitive report")).toBeInTheDocument();
    expect(within(recent).getByText(/A coordinator will contact you/)).toBeInTheDocument();
    expect(within(recent).getByText("Found safe")).toBeInTheDocument();
    expect(within(recent).getByText(/Central Hospital Demo/)).toBeInTheDocument();
    expect(screen.getByText("No notifications yet")).toBeInTheDocument();
    expect(await screen.findByTestId("map")).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("tab", { name: "People" }));
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("link", { name: "Maya R." })).toHaveAttribute(
      "href",
      "/people/per_2",
    );
  });

  it("has no story outside the demo and explains a missing incident", async () => {
    const { api } = routes({ [BASE]: () => ({ ...INCIDENT, is_demo: false }) });
    const view = renderApp(as(), "/incidents/inc_demo", api);
    await screen.findByRole("heading", { name: "Kesari Valley flood (fictional demo)" });
    expect(screen.queryByText(/Step 1 of 4/)).toBeNull();
    view.unmount();

    renderApp(as(), "/incidents/inc_x", routedApi({}).api);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("This incident does not exist.");
  });

  it("draws the graph focused on Maya and explains a selected record", async () => {
    const { api } = routes();
    renderApp(as(), "/incidents/inc_demo", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Graph" }));
    // Focused on Maya: her report, its source and the possible match, not Arjun.
    expect(await screen.findByRole("img", { name: "Graph of 4 records and 3 links" })).toBeInTheDocument();
    expect(screen.getByLabelText("Focus on")).toHaveValue("per_1");
    expect(screen.getByText("Records").closest(".stat")).toHaveTextContent("5");

    await user.click(screen.getByRole("button", { name: "Central Hospital Demo" }));
    const details = screen.getByText("Source", { selector: ".eyebrow" }).closest(".graph-details") as HTMLElement;
    expect(within(details).getByText("1 link")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Focus on"), "");
    expect(screen.getByRole("img", { name: "Graph of 5 records and 3 links" })).toBeInTheDocument();
    await user.click(screen.getByLabelText("Reports"));
    expect(screen.getByRole("img", { name: "Graph of 4 records and 1 links" })).toBeInTheDocument();
  });
});
