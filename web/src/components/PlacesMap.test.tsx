import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ClimateFeature } from "../api/climate";
import type { MapPlace } from "../api/map";
import PlacesMap from "./PlacesMap";

const made = vi.hoisted(() => ({
  maps: [] as {
    options: Record<string, unknown>;
    fitted: unknown;
    removed: boolean;
    handlers: Record<string, () => void>;
    sources: Record<string, Record<string, unknown>>;
    layers: { id: string; paint: Record<string, unknown> }[];
  }[],
  markers: [] as { element: HTMLElement; at: unknown; popup: HTMLElement | null; removed: boolean }[],
}));

vi.mock("maplibre-gl", () => {
  class Map {
    entry: (typeof made.maps)[number];
    constructor(options: Record<string, unknown>) {
      this.entry = { options, fitted: null, removed: false, handlers: {}, sources: {}, layers: [] };
      made.maps.push(this.entry);
    }
    addControl() {}
    on(event: string, handler: () => void) {
      this.entry.handlers[event] = handler;
    }
    addSource(id: string, source: Record<string, unknown>) {
      this.entry.sources[id] = source;
    }
    addLayer(layer: { id: string; paint: Record<string, unknown> }) {
      this.entry.layers.push(layer);
    }
    resize() {}
    fitBounds(bounds: unknown) {
      this.entry.fitted = bounds;
    }
    remove() {
      this.entry.removed = true;
    }
  }
  class Popup {
    content: HTMLElement | null = null;
    setDOMContent(el: HTMLElement) {
      this.content = el;
      return this;
    }
  }
  class Marker {
    entry: (typeof made.markers)[number];
    constructor({ element }: { element: HTMLElement }) {
      this.entry = { element, at: null, popup: null, removed: false };
      made.markers.push(this.entry);
    }
    setLngLat(at: unknown) {
      this.entry.at = at;
      return this;
    }
    setPopup(popup: Popup) {
      this.entry.popup = popup.content;
      return this;
    }
    addTo() {
      return this;
    }
    remove() {
      this.entry.removed = true;
    }
  }
  class LngLatBounds {
    points: unknown[] = [];
    extend(p: unknown) {
      this.points.push(p);
    }
  }
  class NavigationControl {}
  return { Map, Popup, Marker, LngLatBounds, NavigationControl, setWorkerUrl: vi.fn() };
});

function place(overrides: Partial<MapPlace>): MapPlace {
  return {
    location_id: "loc_1",
    name: "Old Bridge",
    lat: 30.73,
    lon: 78.44,
    reports: 4,
    by_status: { MISSING: 3, FOUND_SAFE: 0, NEEDS_REVIEW: 1, OTHER: 0 },
    ...overrides,
  };
}

describe("PlacesMap", () => {
  it("puts a labeled pin per place and fits them all in view", () => {
    made.maps.length = 0;
    made.markers.length = 0;
    const view = render(
      <PlacesMap
        styleUrl="https://tiles.example/style"
        places={[place({}), place({ location_id: "loc_2", name: "Relief Camp", lat: 30.7, lon: 78.4, reports: 1, by_status: { MISSING: 0, FOUND_SAFE: 1, NEEDS_REVIEW: 0, OTHER: 0 } })]}
      />,
    );
    expect(made.maps[0]!.options.style).toBe("https://tiles.example/style");
    const [bridge, camp] = made.markers;
    expect(bridge!.at).toEqual([78.44, 30.73]);
    // Each dot takes the most urgent status at the place, and is named for screen readers.
    expect(bridge!.element).toHaveAccessibleName("Old Bridge: 4 reports, missing");
    expect(bridge!.element).toHaveClass("pin-place", "pin-missing");
    expect(bridge!.element).toHaveTextContent("Old Bridge");
    expect(camp!.element).toHaveAccessibleName("Relief Camp: 1 report, reported safe");
    expect(camp!.element).toHaveClass("pin-found-safe");
    expect(bridge!.popup).toHaveTextContent("Missing: 3");
    expect(bridge!.popup).not.toHaveTextContent("Found safe");
    expect(made.maps[0]!.fitted).toBeTruthy();

    view.unmount();
    expect(made.maps[0]!.removed).toBe(true);
    expect(made.markers.every((m) => m.removed)).toBe(true);
  });

  it("never renders a place name as HTML", () => {
    made.markers.length = 0;
    render(<PlacesMap styleUrl="s" places={[place({ name: '<img src=x onerror="alert(1)">' })]} />);
    const popup = made.markers[0]!.popup!;
    expect(popup.querySelector("img")).toBeNull();
    expect(popup).toHaveTextContent('<img src=x onerror="alert(1)">');
  });

  it("adds a square pin per located condition and flags disagreement", () => {
    made.markers.length = 0;
    const bridge: ClimateFeature = {
      subject_id: "inf_1",
      subject_type: "INFRASTRUCTURE",
      name: "Old Bridge",
      label: "Reported bridge open",
      basis: "Latest dated status report",
      cited_claim_id: "clm_2",
      needs_review: false,
      report_count: 2,
      location: { location_id: "loc_b", name: "Old Bridge", lat: 30.72, lon: 78.43 },
      conflicts: [
        {
          claim_id: "clm_1",
          claim_type: "BRIDGE_DAMAGED",
          source: "District Police Demo",
          reported_at: null,
          excerpt: "<b>Closed</b>",
        },
      ],
      recent: [
        {
          claim_id: "clm_1",
          claim_type: "BRIDGE_DAMAGED",
          source: "District Police Demo",
          reported_at: null,
          excerpt: "<b>Closed</b>",
        },
      ],
    };
    const unplaced = { ...bridge, subject_id: "shl_1", subject_type: "SHELTER" as const, location: null, conflicts: [] };
    render(<PlacesMap styleUrl="s" places={[]} features={[bridge, unplaced]} />);
    expect(made.markers).toHaveLength(1);
    const marker = made.markers[0]!;
    expect(marker.at).toEqual([78.43, 30.72]);
    expect(marker.element).toHaveClass("pin-climate", "pin-infrastructure", "pin-disputed");
    expect(marker.element).toHaveAccessibleName(
      "Old Bridge: Reported bridge open, sources disagree",
    );
    expect(marker.popup).toHaveTextContent("District Police Demo says Bridge damaged");
    expect(marker.popup!.querySelector("b")).toBeNull();
  });

  it("draws the flooded river under the pins once the map loads, credited", () => {
    made.maps.length = 0;
    const river = {
      name: "Trishuli river",
      note: "Course, not flood extent.",
      attribution: "River course: OpenStreetMap contributors (ODbL)",
      coordinates: [
        [85.1561, 27.9363],
        [85.1357, 27.9162],
      ] as [number, number][],
    };
    render(<PlacesMap styleUrl="s" places={[place({ lat: 27.92, lon: 85.14 })]} river={river} />);
    const map = made.maps[0]!;
    // Layers can only be added to a loaded style.
    expect(map.layers).toEqual([]);
    map.handlers.load!();
    const source = map.sources.river as { attribution: string; data: { geometry: unknown } };
    expect(source.attribution).toBe("River course: OpenStreetMap contributors (ODbL)");
    expect(source.data.geometry).toEqual({ type: "LineString", coordinates: river.coordinates });
    // The river under a glow of report counts, so the pins stay on top.
    expect(map.layers.map((l) => l.id)).toEqual(["river-glow", "river", "report-heat"]);
    // The view fits the river as well as the pins.
    expect((map.fitted as { points: unknown[] }).points).toEqual([
      [85.14, 27.92],
      [85.1561, 27.9363],
      [85.1357, 27.9162],
    ]);
  });

  it("adds no river when the incident has none", () => {
    made.maps.length = 0;
    render(<PlacesMap styleUrl="s" places={[place({})]} />);
    made.maps[0]!.handlers.load!();
    expect(made.maps[0]!.layers.map((l) => l.id)).toEqual(["report-heat"]);
  });

  it("draws the district and other rivers faintly, beneath the flooded river", () => {
    made.maps.length = 0;
    const context = {
      attribution: "OpenStreetMap contributors",
      rivers: [{ name: "Tadi Khola", coordinates: [[85.2, 27.9], [85.18, 27.88]] as [number, number][] }],
      district: {
        name: "Nuwakot district",
        coordinates: [[85.0, 27.8], [85.4, 28.0]] as [number, number][],
      },
    };
    const river = {
      name: "Trishuli river",
      note: "Course.",
      attribution: "OpenStreetMap contributors",
      coordinates: [[85.15, 27.93], [85.14, 27.92]] as [number, number][],
    };
    render(<PlacesMap styleUrl="s" places={[]} river={river} context={context} />);
    const map = made.maps[0]!;
    map.handlers.load!();
    expect(map.layers.map((l) => l.id)).toEqual(["district", "other-rivers", "river-glow", "river"]);
    // The view stays on the town: the district is far larger and is not fitted.
    expect((map.fitted as { points: unknown[] }).points).toEqual(river.coordinates);
  });

  it("weights the report glow by each place's share of the busiest", () => {
    made.maps.length = 0;
    render(
      <PlacesMap
        styleUrl="s"
        places={[place({ reports: 8 }), place({ location_id: "loc_2", reports: 2 })]}
      />,
    );
    const map = made.maps[0]!;
    map.handlers.load!();
    const heat = map.sources["report-heat"] as {
      data: { features: { properties: { weight: number } }[] };
    };
    expect(heat.data.features.map((f) => f.properties.weight)).toEqual([1, 0.25]);
  });
});
