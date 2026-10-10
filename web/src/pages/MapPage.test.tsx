import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ClimateFeature } from "../api/climate";
import type { IncidentMap, MapPlace } from "../api/map";
import { mapStyleUrl } from "../api/map";
import { FakeGateway, REVIEWER, renderApp, routedApi } from "../test/fakes";

vi.mock("../components/PlacesMap", () => ({
  default: ({
    places,
    features = [],
    styleUrl,
  }: {
    places: MapPlace[];
    features?: ClimateFeature[];
    styleUrl: string;
  }) => (
    <div data-testid="map" data-style={styleUrl}>
      {places.length} pins, {features.length} conditions
    </div>
  ),
}));

const PATH = "/v1/incidents/inc_1/map";
const CLIMATE = "/v1/incidents/inc_1/climate";

function feature(overrides: Partial<ClimateFeature> = {}): ClimateFeature {
  return {
    subject_id: "inf_1",
    subject_type: "INFRASTRUCTURE",
    name: "Old Bridge",
    label: "Reported bridge open",
    basis: "Latest dated status report",
    cited_claim_id: "clm_2",
    needs_review: false,
    report_count: 2,
    location: { location_id: "loc_bridge", name: "Old Bridge", lat: 30.73, lon: 78.44 },
    conflicts: [
      {
        claim_id: "clm_1",
        claim_type: "BRIDGE_DAMAGED",
        source: "District Police Demo",
        reported_at: "2026-10-02T14:40:00Z",
        excerpt: "Old Bridge closed.",
      },
    ],
    recent: [],
    ...overrides,
  };
}

const SHELTER = feature({
  subject_id: "shl_1",
  subject_type: "SHELTER",
  name: "Riverside Shelter",
  label: "Reported shelter full",
  conflicts: [],
  location: null,
});

function climate(features: ClimateFeature[] = [feature(), SHELTER]) {
  return () => ({
    features,
    caveat: "Places and conditions are as reported and unverified.",
    updated_at: "2026-10-05T10:15:00Z",
  });
}

const BRIDGE: MapPlace = {
  location_id: "loc_bridge",
  name: "Old Bridge",
  lat: 30.73,
  lon: 78.44,
  reports: 41,
  by_status: { MISSING: 12, FOUND_SAFE: 20, NEEDS_REVIEW: 3, OTHER: 6 },
};

function body(overrides: Partial<IncidentMap> = {}): IncidentMap {
  return {
    places: [BRIDGE],
    located_reports: 41,
    unlocated_reports: 9,
    caveat: "Locations are as reported and unverified. Counts are reports, not unique people.",
    updated_at: "2026-10-05T10:15:00Z",
    ...overrides,
  };
}

function renderMap(api: ReturnType<typeof routedApi>["api"], styleUrl?: string) {
  const gateway = new FakeGateway();
  gateway.user = REVIEWER;
  return renderApp(gateway, "/incidents/inc_1/map", api, { mapStyleUrl: styleUrl });
}

afterEach(() => localStorage.clear());

describe("map page", () => {
  it("shows the caveat, the totals and a table of places", async () => {
    const { api } = routedApi({ [PATH]: () => body(), [CLIMATE]: climate() });
    renderMap(api);
    expect((await screen.findAllByRole("note"))[0]).toHaveTextContent("Counts are reports");
    expect(screen.getByText(/41 reports with a place, 9 without/)).toBeInTheDocument();
    const row = screen.getByRole("row", { name: /Old Bridge/ });
    expect(within(row).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "41",
      "12",
      "20",
      "3",
      "6",
    ]);
  });

  it("draws the map only when a basemap is configured", async () => {
    const { api } = routedApi({ [PATH]: () => body(), [CLIMATE]: climate() });
    const view = renderMap(api);
    expect(await screen.findByText(/basemap is not set up/)).toBeInTheDocument();
    expect(screen.queryByTestId("map")).not.toBeInTheDocument();
    view.unmount();

    renderMap(api, "https://tiles.example/style");
    const map = await screen.findByTestId("map");
    expect(map).toHaveAttribute("data-style", "https://tiles.example/style");
    expect(map).toHaveTextContent("1 pins, 2 conditions");
  });

  it("says when no report has coordinates yet", async () => {
    const { api } = routedApi({ [PATH]: () => body({ places: [], located_reports: 0 }), [CLIMATE]: climate([]) });
    renderMap(api, "https://tiles.example/style");
    expect(await screen.findByText("No reports with coordinates yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("map")).not.toBeInTheDocument();
  });

  it("refreshes on request", async () => {
    let calls = 0;
    const { api } = routedApi({
      [PATH]: () => body({ located_reports: ++calls === 1 ? 41 : 42 }),
      [CLIMATE]: climate(),
    });
    renderMap(api);
    await screen.findByText(/41 reports with a place/);
    await userEvent.setup().click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText(/42 reports with a place/)).toBeInTheDocument();
  });

  it("explains an unknown incident", async () => {
    renderMap(routedApi({}).api);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("This incident does not exist.");
  });
});

describe("climate layers", () => {
  it("lists conditions with disagreeing sources flagged", async () => {
    const { api } = routedApi({ [PATH]: () => body(), [CLIMATE]: climate() });
    renderMap(api);
    expect(await screen.findByText("Sources disagree")).toBeInTheDocument();
    expect(screen.getByText(/District Police Demo says Bridge damaged/)).toBeInTheDocument();
    expect(screen.getByText(/Reported shelter full/)).toBeInTheDocument();
    expect(screen.getByText(/No place given/)).toBeInTheDocument();
  });

  it("turns layers on and off", async () => {
    const { api } = routedApi({ [PATH]: () => body(), [CLIMATE]: climate() });
    renderMap(api, "https://tiles.example/style");
    const map = await screen.findByTestId("map");
    await screen.findByText("Sources disagree");
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Reports about people"));
    expect(map).toHaveTextContent("0 pins, 2 conditions");
    await user.click(screen.getByLabelText("Shelters"));
    expect(map).toHaveTextContent("0 pins, 1 conditions");
    expect(screen.queryByText(/Reported shelter full/)).toBeNull();
    // Only layers with something in them are offered.
    expect(screen.queryByLabelText("Hazards")).toBeNull();
  });

  it("keeps the people map when the climate layer fails", async () => {
    const { api } = routedApi({ [PATH]: () => body() });
    renderMap(api);
    expect(await screen.findByText(/41 reports with a place/)).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Not found.");
    expect(screen.getByRole("row", { name: /Old Bridge/ })).toBeInTheDocument();
  });
});

describe("mapStyleUrl", () => {
  it("builds the Amazon Location style URL with the key", () => {
    expect(mapStyleUrl("ap-south-1", "v1.public.abc")).toBe(
      "https://maps.geo.ap-south-1.amazonaws.com/v2/styles/Standard/descriptor?key=v1.public.abc",
    );
    expect(mapStyleUrl("ap-south-1", "k", true)).toMatch(/color-scheme=Dark$/);
  });
});
