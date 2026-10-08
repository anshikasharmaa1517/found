import "maplibre-gl/dist/maplibre-gl.css";

import {
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  Popup,
} from "maplibre-gl";
import { useEffect, useRef } from "react";

import { BUCKET_LABELS, BUCKETS, type MapPlace } from "../api/map";

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

export default function PlacesMap({ places, styleUrl }: { places: MapPlace[]; styleUrl: string }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const first = places[0];
    const map = new MapLibreMap({
      container: container.current,
      style: styleUrl,
      center: first ? [first.lon, first.lat] : DEFAULT_CENTER,
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
    if (places.length > 1) {
      const bounds = new LngLatBounds();
      for (const place of places) bounds.extend([place.lon, place.lat]);
      map.fitBounds(bounds, { padding: 48, maxZoom: 13, duration: 0 });
    }
    return () => {
      for (const marker of markers) marker.remove();
      map.remove();
    };
  }, [places, styleUrl]);

  return <div ref={container} className="map" role="region" aria-label="Map of reported places" />;
}
