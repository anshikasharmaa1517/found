import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RecentReport } from "../api/incidents";
import { userFromClaims } from "../auth/user";
import { FakeGateway, REVIEWER, renderApp, routedApi } from "../test/fakes";

const FAMILY = userFromClaims({ sub: "f", name: "Asha", "cognito:groups": ["family"] });
const PUBLISHER = userFromClaims({
  sub: "p",
  "cognito:groups": ["publisher"],
  "custom:org_id": "org_h",
});
const ADMIN = userFromClaims({ sub: "a", "cognito:groups": ["admin"] });

vi.mock("./PlacesMap", () => ({
  default: () => <div data-testid="map">map</div>,
}));

const BASE = "/v1/incidents/inc_demo";
const INCIDENT = {
  id: "inc_demo",
  name: "Melamchi flood (fictional demo)",
  area: "Melamchi, Sindhupalchok, Nepal (fictional scenario)",
  is_demo: true,
  started_at: "2026-10-02T13:00:00Z",
};
const RECENT: RecentReport[] = [
  {
    claim_id: "clm_9",
    subject_id: "per_9",
    subject_type: "PERSON",
    subject_name: "Gopal Adhikari",
    ingested_at: "2026-10-05T10:15:00Z",
    withheld: true,
    notice: "A sensitive report was received. A coordinator will contact you.",
  },
  {
    claim_id: "clm_2",
    subject_id: "per_1",
    subject_type: "PERSON",
    subject_name: "Sita Tamang",
    ingested_at: "2026-10-05T10:10:00Z",
    withheld: false,
    claim_type: "FOUND_SAFE",
    source: "Central Hospital Demo",
    reported_at: "2026-10-03T02:10:00Z",
    excerpt: "Sita Tamang, 24, admitted to ward 3.",
  },
];

function routes(
  overrides: Record<string, () => unknown> = {},
  posts: Record<string, (body: unknown) => unknown> = {},
) {
  return routedApi(
    {
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
        { id: "per_1", name: "Sita Tamang", age: 24 },
        { id: "per_2", name: "Sita T.", age: 24 },
      ],
      next_cursor: null,
    }),
    "/v1/people/per_1/timeline": () => ({
      person: { id: "per_1", name: "Sita Tamang", age: 24 },
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
          excerpt: "Sita Tamang admitted.",
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
          excerpt: "According to Central Hospital Demo, Sita is safe.",
        },
      ],
      next_cursor: null,
    }),
    [`${BASE}/graph`]: () => ({
      nodes: [
        { id: "per_1", kind: "person", label: "Sita Tamang", detail: "Age 24", subject_type: "PERSON" },
        { id: "per_2", kind: "person", label: "Sita T.", detail: "Age 24", subject_type: "PERSON" },
        { id: "clm_2", kind: "report", label: "Found safe", detail: "Central Hospital Demo", subject_type: null },
        { id: "src_h", kind: "source", label: "Central Hospital Demo", detail: null, subject_type: null },
        { id: "per_3", kind: "person", label: "Bikash Shrestha", detail: null, subject_type: "PERSON" },
      ],
      edges: [
        { source: "clm_2", target: "per_1", kind: "about" },
        { source: "clm_2", target: "src_h", kind: "from" },
        { source: "per_1", target: "per_2", kind: "possibly_same" },
      ],
      by_kind: { person: 3, report: 1, source: 1 },
    }),
    ...overrides,
    },
    posts,
  );
}

function as(user = REVIEWER) {
  const gateway = new FakeGateway();
  gateway.user = user;
  return gateway;
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

function tabNames() {
  return within(screen.getByRole("navigation", { name: "Main" }))
    .getAllByRole("link")
    .map((a) => a.textContent);
}

describe("app shell", () => {
  it("names the incident, opens on the map and walks through the demo story", async () => {
    const { api } = routes();
    renderApp(as(), "/incidents/inc_demo", api, { mapStyleUrl: "https://tiles.example/style" });
    const masthead = await screen.findByRole("banner");
    expect(
      await within(masthead).findByText("Melamchi flood (fictional demo)"),
    ).toBeInTheDocument();
    expect(within(masthead).getByText(/Melamchi, Sindhupalchok, Nepal/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Map", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Map" })).toHaveAttribute("aria-current", "page");

    expect(await screen.findByRole("heading", { name: "Sita is reported missing" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See every report about Sita" })).toHaveAttribute(
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

  it("shows each role its own tabs", async () => {
    const { api } = routes({ "/v1/me/alerts": () => ({ alerts: [], next_cursor: null }) });
    const view = renderApp(as(), "/incidents/inc_demo/map", api);
    await screen.findByRole("heading", { name: "Map" });
    expect(tabNames()).toEqual(["Map", "People", "Sources", "Graph", "Review"]);
    view.unmount();

    const publisher = renderApp(as(PUBLISHER), "/incidents/inc_demo/map", api);
    await screen.findByRole("heading", { name: "Map" });
    expect(tabNames()).toEqual(["Map", "People", "Sources", "Graph", "Report", "Upload"]);
    publisher.unmount();

    renderApp(as(FAMILY), "/incidents/inc_demo/map", api);
    await screen.findByRole("heading", { name: "Map" });
    expect(tabNames()).toEqual(["Map", "People", "Sources", "Graph", "Alerts"]);
  });

  it("keeps the People tab current on a person's page", async () => {
    const { api } = routes();
    localStorage.setItem("found.incidentId", "inc_demo");
    renderApp(as(), "/people/per_1", api);
    await screen.findByRole("heading", { name: "Sita Tamang", level: 1 });
    expect(screen.getByRole("link", { name: "People" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Map" })).not.toHaveAttribute("aria-current");
  });

  it("gives families the other record instead of the review queue", async () => {
    const { api } = routes({ "/v1/me/alerts": () => ({ alerts: [], next_cursor: null }) });
    renderApp(as(FAMILY), "/incidents/inc_demo", api);
    await screen.findByRole("heading", { name: "Sita is reported missing" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Next step" }));
    expect(screen.getByRole("link", { name: "See the other record" })).toHaveAttribute(
      "href",
      "/people/per_2",
    );
    expect(await screen.findByText(/Follow a person from their page/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start over" })).toBeNull();
  });

  it("hides the story guide and remembers it", async () => {
    const { api } = routes();
    const view = renderApp(as(), "/incidents/inc_demo", api);
    await screen.findByRole("heading", { name: "Sita is reported missing" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Hide story guide" }));
    expect(screen.queryByRole("heading", { name: "Sita is reported missing" })).toBeNull();
    expect(screen.getByRole("button", { name: "Show story guide" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    view.unmount();

    renderApp(as(), "/incidents/inc_demo", api);
    expect(await screen.findByRole("button", { name: "Show story guide" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sita is reported missing" })).toBeNull();
  });

  it("lets an admin start the demo over after confirming", async () => {
    const reset = vi.fn(() => ({ incident_id: "inc_demo", status: "RESETTING" }));
    const { api } = routes({}, { "/v1/admin/incidents/inc_demo/reset": reset });
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    renderApp(as(ADMIN), "/incidents/inc_demo", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Start over" }));
    expect(reset).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Start over" }));
    expect(await screen.findByText(/The demo is reloading/)).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("shows recent updates beside the work, with sensitive reports masked", async () => {
    const { api } = routes();
    renderApp(as(), "/incidents/inc_demo", api, { mapStyleUrl: "https://tiles.example/style" });
    const rail = await screen.findByRole("complementary", {
      name: "Notifications and recent updates",
    });
    const recent = (await within(rail).findByRole("heading", { name: "Recent updates" })).closest(
      "section",
    )!;
    expect(await within(recent).findByText("Sensitive report")).toBeInTheDocument();
    expect(within(recent).getByText(/A coordinator will contact you/)).toBeInTheDocument();
    expect(within(recent).getByText("Found safe")).toBeInTheDocument();
    expect(within(recent).getByText(/Central Hospital Demo/)).toBeInTheDocument();
    expect(within(rail).getByText("No notifications yet")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toHaveTextContent(/confirm with the source/);

    await userEvent.setup().click(screen.getByRole("link", { name: "People" }));
    const list = await screen.findByRole("list", { name: "People" });
    expect(within(list).getByRole("link", { name: "Sita T." })).toHaveAttribute(
      "href",
      "/people/per_2",
    );
  });

  it("has no story outside the demo and explains a missing incident", async () => {
    const { api } = routes({ [BASE]: () => ({ ...INCIDENT, is_demo: false }) });
    const view = renderApp(as(), "/incidents/inc_demo", api);
    await screen.findByText("Melamchi flood (fictional demo)");
    await screen.findByRole("heading", { name: "Map" });
    expect(screen.queryByText(/Step 1 of 4/)).toBeNull();
    view.unmount();

    renderApp(as(), "/incidents/inc_x", routedApi({}).api);
    expect(await screen.findByText("This incident does not exist.")).toBeInTheDocument();
    expect(screen.getAllByRole("banner")[0]).toHaveTextContent("inc_x");
  });

  it("draws the graph focused on Sita and explains a selected record", async () => {
    const { api } = routes();
    renderApp(as(), "/incidents/inc_demo", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("link", { name: "Graph" }));
    expect(screen.getByRole("link", { name: "Graph" })).toHaveAttribute("aria-current", "page");
    // Focused on Sita: her report, its source and the possible match, not Bikash.
    expect(await screen.findByRole("img", { name: "Graph of 4 records and 3 links" })).toBeInTheDocument();
    expect(screen.getByLabelText("Focus on")).toHaveValue("per_1");
    expect(screen.getByText("Records").closest(".stat")).toHaveTextContent("5");

    await user.click(screen.getByRole("button", { name: "Central Hospital Demo" }));
    const details = screen
      .getByText("Source", { selector: ".eyebrow" })
      .closest(".graph-details") as HTMLElement;
    expect(within(details).getByText("1 link")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Focus on"), "");
    expect(screen.getByRole("img", { name: "Graph of 5 records and 3 links" })).toBeInTheDocument();
    await user.click(screen.getByLabelText("Reports"));
    expect(screen.getByRole("img", { name: "Graph of 4 records and 1 links" })).toBeInTheDocument();
  });
});
