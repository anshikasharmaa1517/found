import "maplibre-gl/dist/maplibre-gl.css";

import {
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  Popup,
  setWorkerUrl,
} from "maplibre-gl";
// MapLibre looks for its worker next to its own file, which no longer exists once it is
// bundled. Ship the worker as its own asset and say where it is, or no tiles load.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef } from "react";

import { CLIMATE_TYPE_LABELS, plotted, type ClimateFeature } from "../api/climate";
import type { MapContext, MapLine, RiverCourse } from "../api/incidents";
import {
  BUCKET_LABELS,
  BUCKETS,
  PLACE_STATUS_LABELS,
  placeStatus,
  type MapPlace,
} from "../api/map";
import { claimTypeLabel, formatTime } from "../labels";

setWorkerUrl(workerUrl);

// Fallback view when there is nothing to fit: Trishuli Bazar, Nepal.
const DEFAULT_CENTER: [number, number] = [85.146, 27.922];

/** Built from text nodes only: place names come from reports and are never treated as HTML. */
function popupContent(place: MapPlace): HTMLElement {
  const box = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = place.name;
  box.append(title);
  const total = document.createElement("p");
  total.textContent = `${place.reports} report${place.reports === 1 ? "" : "s"}`;
  box.append(total);
  const list = document.createElement("ul");
  for (const bucket of BUCKETS) {
    if (!place.by_status[bucket]) continue;
    const item = document.createElement("li");
    item.textContent = `${BUCKET_LABELS[bucket]}: ${place.by_status[bucket]}`;
    list.append(item);
  }
  box.append(list);
  return box;
}

function line(tag: string, text: string): HTMLElement {
  const el = document.createElement(tag);
  el.textContent = text;
  return el;
}

/** Text nodes only, as for places: names and excerpts come from reports. */
function featureContent(feature: ClimateFeature): HTMLElement {
  const box = document.createElement("div");
  box.append(line("strong", feature.name));
  box.append(line("p", `${CLIMATE_TYPE_LABELS[feature.subject_type]}. ${feature.label}.`));
  box.append(line("p", feature.basis));
  if (feature.conflicts.length > 0) {
    box.append(line("p", "Sources disagree:"));
    const list = document.createElement("ul");
    for (const c of feature.conflicts) {
      list.append(line("li", `${c.source} says ${claimTypeLabel(c.claim_type)}`));
    }
    box.append(list);
  }
  const recent = document.createElement("ul");
  for (const r of feature.recent) {
    recent.append(line("li", `${r.source}, ${formatTime(r.reported_at)}: ${r.excerpt}`));
  }
  box.append(recent);
  return box;
}

function featurePin(feature: ClimateFeature): HTMLElement {
  const el = document.createElement("button");
  el.type = "button";
  const disputed = feature.conflicts.length > 0 || feature.needs_review;
  el.className = `pin pin-climate pin-${feature.subject_type.toLowerCase()}${disputed ? " pin-disputed" : ""}`;
  el.textContent = CLIMATE_TYPE_LABELS[feature.subject_type].charAt(0);
  el.setAttribute(
    "aria-label",
    `${feature.name}: ${feature.label}${disputed ? ", sources disagree" : ""}`,
  );
  return el;
}

/** A dot in the place's status color, with its name beside it. */
function pin(place: MapPlace): HTMLElement {
  const status = placeStatus(place);
  const el = document.createElement("button");
  el.type = "button";
  el.className = `pin pin-place pin-${status.toLowerCase().replace("_", "-")}`;
  el.setAttribute(
    "aria-label",
    `${place.name}: ${place.reports} report${place.reports === 1 ? "" : "s"}, ${PLACE_STATUS_LABELS[status].toLowerCase()}`,
  );
  const label = line("span", place.name);
  label.className = "pin-label";
  el.append(label);
  return el;
}

/** A theme color for the map, which paints with plain colors, not CSS variables. */
function mapColor(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function lineFeature(line: MapLine | RiverCourse) {
  return {
    type: "Feature" as const,
    properties: { name: line.name ?? "" },
    geometry: { type: "LineString" as const, coordinates: line.coordinates },
  };
}

/** The district and the other rivers, faint, under everything else. */
function drawContext(map: MapLibreMap, context: MapContext) {
  if (context.district) {
    map.addSource("district", {
      type: "geojson",
      attribution: context.attribution,
      data: lineFeature(context.district),
    });
    map.addLayer({
      id: "district",
      type: "line",
      source: "district",
      layout: { "line-join": "round" },
      paint: {
        "line-color": mapColor("--district", "#8b8cf8"),
        "line-opacity": 0.9,
        "line-width": 2.5,
      },
    });
  }
  if (context.rivers.length > 0) {
    map.addSource("other-rivers", {
      type: "geojson",
      attribution: context.attribution,
      data: { type: "FeatureCollection", features: context.rivers.map(lineFeature) },
    });
    map.addLayer({
      id: "other-rivers",
      type: "line",
      source: "other-rivers",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": mapColor("--river", "#58a6ff"),
        "line-opacity": 0.8,
        "line-width": 1.5,
      },
    });
  }
}

/** The river that flooded: a soft glow, then the line. */
function drawRiver(map: MapLibreMap, river: RiverCourse) {
  const color = mapColor("--flood-river", "#f2c94c");
  map.addSource("river", {
    type: "geojson",
    attribution: river.attribution,
    data: lineFeature(river),
  });
  map.addLayer({
    id: "river-glow",
    type: "line",
    source: "river",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": color, "line-opacity": 0.45, "line-width": 14, "line-blur": 8 },
  });
  map.addLayer({
    id: "river",
    type: "line",
    source: "river",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": color, "line-opacity": 0.95, "line-width": 4 },
  });
}

/** A glow under the pins: blue where few reports were made, through yellow, to red. */
function drawHeat(map: MapLibreMap, places: MapPlace[]) {
  const largest = Math.max(...places.map((p) => p.reports), 1);
  map.addSource("report-heat", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: places.map((p) => ({
        type: "Feature" as const,
        properties: { weight: p.reports / largest },
        geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] },
      })),
    },
  });
  map.addLayer({
    id: "report-heat",
    type: "heatmap",
    source: "report-heat",
    paint: {
      "heatmap-weight": ["get", "weight"],
      "heatmap-intensity": 3,
      "heatmap-radius": ["interpolate", ["exponential", 2], ["zoom"], 10, 24, 16, 140],
      "heatmap-opacity": 0.75,
      "heatmap-color": [
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0,
        "rgba(0, 0, 0, 0)",
        0.15,
        mapColor("--heat-low", "#2f6bff"),
        0.5,
        mapColor("--heat-mid", "#f2c94c"),
        0.85,
        mapColor("--heat-high", "#ff5a5f"),
      ],
    },
  });
}

function overlaps(a: DOMRect, b: DOMRect): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

/** Hides a name that would cover a busier place's name; its dot and popup stay. */
function declutter(pins: { element: HTMLElement; reports: number }[]) {
  const shown: DOMRect[] = [];
  for (const { element } of [...pins].sort((a, b) => b.reports - a.reports)) {
    const label = element.querySelector<HTMLElement>(".pin-label");
    if (!label) continue;
    label.hidden = false;
    const box = label.getBoundingClientRect();
    label.hidden = shown.some((other) => overlaps(box, other));
    if (!label.hidden) shown.push(box);
  }
}

export default function PlacesMap({
  places,
  features = [],
  river = null,
  context = null,
  styleUrl,
}: {
  places: MapPlace[];
  features?: ClimateFeature[];
  /** The river that flooded, drawn under the pins. */
  river?: RiverCourse | null;
  /** Other rivers and the district, drawn faintly for orientation. */
  context?: MapContext | null;
  styleUrl: string;
}) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const located = features.filter(plotted);
    const points: [number, number][] = [
      ...places.map((p): [number, number] => [p.lon, p.lat]),
      ...located.map((f): [number, number] => [f.location.lon, f.location.lat]),
      ...(river?.coordinates ?? []),
    ];
    const map = new MapLibreMap({
      container: container.current,
      style: styleUrl,
      center: points[0] ?? DEFAULT_CENTER,
      zoom: 10,
      attributionControl: { compact: true },
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    // Layers can only be added once the style has loaded; the pins sit above them all.
    map.on("load", () => {
      if (context) drawContext(map, context);
      if (river) drawRiver(map, river);
      if (places.length > 0) drawHeat(map, places);
    });

    const pins = places.map((place) => ({ element: pin(place), reports: place.reports }));
    // Names come back as the map zooms in and places move apart.
    map.on("moveend", () => declutter(pins));
    const markers = places.map((place, i) =>
      new Marker({ element: pins[i]!.element })
        .setLngLat([place.lon, place.lat])
        .setPopup(new Popup({ offset: 14 }).setDOMContent(popupContent(place)))
        .addTo(map),
    );
    for (const feature of located) {
      markers.push(
        // Offset up and left, so a condition never hides the name beside a place's dot.
        new Marker({ element: featurePin(feature), offset: [-16, -16] })
          .setLngLat([feature.location.lon, feature.location.lat])
          .setPopup(new Popup({ offset: 14 }).setDOMContent(featureContent(feature)))
          .addTo(map),
      );
    }
    function fit() {
      if (points.length < 2) return;
      const bounds = new LngLatBounds();
      for (const point of points) bounds.extend(point);
      map.fitBounds(bounds, { padding: 64, maxZoom: 15, duration: 0 });
    }
    fit();
    // The map sizes its canvas once; redraw whenever the box it sits in changes size.
    const resize =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            map.resize();
            fit();
          });
    resize?.observe(container.current);
    return () => {
      resize?.disconnect();
      for (const marker of markers) marker.remove();
      map.remove();
    };
  }, [places, features, river, context, styleUrl]);

  return <div ref={container} className="map" role="region" aria-label="Map of reported places and conditions" />;
}
