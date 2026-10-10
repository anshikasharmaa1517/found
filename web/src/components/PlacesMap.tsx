import "maplibre-gl/dist/maplibre-gl.css";

import {
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  Popup,
} from "maplibre-gl";
import { useEffect, useRef } from "react";

import { CLIMATE_TYPE_LABELS, plotted, type ClimateFeature } from "../api/climate";
import { BUCKET_LABELS, BUCKETS, type MapPlace } from "../api/map";
import { claimTypeLabel, formatTime } from "../labels";

// Fallback view when there is nothing to fit: the demo region in Uttarakhand.
const DEFAULT_CENTER: [number, number] = [78.4, 30.7];

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

function pin(place: MapPlace, largest: number): HTMLElement {
  const el = document.createElement("button");
  el.type = "button";
  el.className = place.by_status.NEEDS_REVIEW > 0 ? "pin pin-review" : "pin";
  el.textContent = String(place.reports);
  el.setAttribute("aria-label", `${place.name}: ${place.reports} reports`);
  const size = Math.round(24 + 24 * Math.sqrt(place.reports / Math.max(largest, 1)));
  el.style.width = `${size}px`;
  el.style.height = `${size}px`;
  return el;
}

export default function PlacesMap({
  places,
  features = [],
  styleUrl,
}: {
  places: MapPlace[];
  features?: ClimateFeature[];
  styleUrl: string;
}) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const located = features.filter(plotted);
    const points: [number, number][] = [
      ...places.map((p): [number, number] => [p.lon, p.lat]),
      ...located.map((f): [number, number] => [f.location.lon, f.location.lat]),
    ];
    const map = new MapLibreMap({
      container: container.current,
      style: styleUrl,
      center: points[0] ?? DEFAULT_CENTER,
      zoom: 10,
      attributionControl: { compact: true },
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");

    const largest = Math.max(...places.map((p) => p.reports), 1);
    const markers = places.map((place) =>
      new Marker({ element: pin(place, largest) })
        .setLngLat([place.lon, place.lat])
        .setPopup(new Popup({ offset: 14 }).setDOMContent(popupContent(place)))
        .addTo(map),
    );
    for (const feature of located) {
      markers.push(
        new Marker({ element: featurePin(feature) })
          .setLngLat([feature.location.lon, feature.location.lat])
          .setPopup(new Popup({ offset: 14 }).setDOMContent(featureContent(feature)))
          .addTo(map),
      );
    }
    if (points.length > 1) {
      const bounds = new LngLatBounds();
      for (const point of points) bounds.extend(point);
      map.fitBounds(bounds, { padding: 48, maxZoom: 13, duration: 0 });
    }
    return () => {
      for (const marker of markers) marker.remove();
      map.remove();
    };
  }, [places, features, styleUrl]);

  return <div ref={container} className="map" role="region" aria-label="Map of reported places and conditions" />;
}
