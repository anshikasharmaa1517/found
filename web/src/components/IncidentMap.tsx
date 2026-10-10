import { lazy, Suspense } from "react";
import { Link } from "react-router-dom";

import { getClimateLayer } from "../api/climate";
import { useApi } from "../api/context";
import { getIncidentMap } from "../api/map";
import { useLoad } from "../useLoad";
import { ErrorNotice } from "./ErrorNotice";
import { MapLegend } from "./MapLegend";
import { SkeletonRows } from "./ui";

const PlacesMap = lazy(() => import("./PlacesMap"));

/** The incident's map with its legend: people pins and climate conditions together. */
export function IncidentMap({
  incidentId,
  mapStyleUrl,
}: {
  incidentId: string;
  mapStyleUrl?: string;
}) {
  const api = useApi();
  const [places, retry] = useLoad(`map|${incidentId}`, () => getIncidentMap(api, incidentId));
  const [climate] = useLoad(`climate|${incidentId}`, () => getClimateLayer(api, incidentId));
  const features = climate.status === "ready" ? climate.data.features : [];

  if (places.status === "loading") return <SkeletonRows label="Loading the map" rows={6} />;
  if (places.status === "error") return <ErrorNotice error={places.error} onRetry={retry} />;

  const listLink = (
    <Link to={`/incidents/${encodeURIComponent(incidentId)}/map`}>
      Open the full map with counts per place
    </Link>
  );
  if (!mapStyleUrl) {
    return (
      <p className="notice-box">
        The basemap is not set up here. {listLink}
      </p>
    );
  }
  return (
    <>
      <div className="map-frame">
        <Suspense fallback={<SkeletonRows label="Loading the map" rows={6} />}>
          <PlacesMap places={places.data.places} features={features} styleUrl={mapStyleUrl} />
        </Suspense>
        <MapLegend />
      </div>
      <p className="meta">
        {places.data.located_reports} reports with a place, {places.data.unlocated_reports}{" "}
        without. {listLink}
      </p>
    </>
  );
}
