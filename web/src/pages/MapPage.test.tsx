import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IncidentMap, MapPlace } from "../api/map";
import { mapStyleUrl } from "../api/map";
import { FakeGateway, REVIEWER, renderApp, routedApi } from "../test/fakes";

vi.mock("../components/PlacesMap", () => ({
  default: ({ places, styleUrl }: { places: MapPlace[]; styleUrl: string }) => (
    <div data-testid="map" data-style={styleUrl}>
      {places.length} pins
    </div>
  ),
}));

const PATH = "/v1/incidents/inc_1/map";

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
    const { api } = routedApi({ [PATH]: () => body() });
    renderMap(api);
    expect(await screen.findByRole("note")).toHaveTextContent("as reported and unverified");
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
    const { api } = routedApi({ [PATH]: () => body() });
    const view = renderMap(api);
    expect(await screen.findByText(/basemap is not set up/)).toBeInTheDocument();
    expect(screen.queryByTestId("map")).not.toBeInTheDocument();
    view.unmount();

    renderMap(api, "https://tiles.example/style");
    const map = await screen.findByTestId("map");
    expect(map).toHaveAttribute("data-style", "https://tiles.example/style");
    expect(map).toHaveTextContent("1 pins");
  });

  it("says when no report has coordinates yet", async () => {
    const { api } = routedApi({ [PATH]: () => body({ places: [], located_reports: 0 }) });
    renderMap(api, "https://tiles.example/style");
    expect(await screen.findByText("No reports with coordinates yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("map")).not.toBeInTheDocument();
  });

  it("refreshes on request", async () => {
    let calls = 0;
    const { api } = routedApi({
      [PATH]: () => body({ located_reports: ++calls === 1 ? 41 : 42 }),
    });
    renderMap(api);
    await screen.findByText(/41 reports with a place/);
    await userEvent.setup().click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText(/42 reports with a place/)).toBeInTheDocument();
  });

  it("explains an unknown incident", async () => {
    renderMap(routedApi({}).api);
    expect(await screen.findByRole("alert")).toHaveTextContent("This incident does not exist.");
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
