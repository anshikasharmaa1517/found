import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MapPlace } from "../api/map";
import PlacesMap from "./PlacesMap";

const made = vi.hoisted(() => ({
  maps: [] as { options: Record<string, unknown>; fitted: unknown; removed: boolean }[],
  markers: [] as { element: HTMLElement; at: unknown; popup: HTMLElement | null; removed: boolean }[],
}));

vi.mock("maplibre-gl", () => {
  class Map {
    entry: (typeof made.maps)[number];
    constructor(options: Record<string, unknown>) {
      this.entry = { options, fitted: null, removed: false };
      made.maps.push(this.entry);
    }
    addControl() {}
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
  return { Map, Popup, Marker, LngLatBounds, NavigationControl };
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
    expect(bridge!.element).toHaveAccessibleName("Old Bridge: 4 reports");
    expect(bridge!.element).toHaveClass("pin-review");
    expect(camp!.element).not.toHaveClass("pin-review");
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
});
