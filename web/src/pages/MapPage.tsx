import { lazy, Suspense, useEffect } from "react";
import { useParams } from "react-router-dom";

import { useApi } from "../api/context";
import { BUCKET_LABELS, BUCKETS, getIncidentMap, type IncidentMap } from "../api/map";
import { ErrorNotice } from "../components/ErrorNotice";
import { rememberIncident } from "../incident";
import { formatTime } from "../labels";
import { useLoad } from "../useLoad";

// Map code is large and needs WebGL, so it loads only when a map is shown.
const PlacesMap = lazy(() => import("../components/PlacesMap"));

function PlacesTable({ data }: { data: IncidentMap }) {
  if (data.places.length === 0) {
    return <p className="muted">No reports with coordinates yet.</p>;
  }
  return (
    <div className="table-wrap">
      <table>
        <caption>Reports per place</caption>
        <thead>
          <tr>
            <th scope="col">Place</th>
            <th scope="col">Reports</th>
            {BUCKETS.map((b) => (
              <th scope="col" key={b}>
                {BUCKET_LABELS[b]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.places.map((place) => (
            <tr key={place.location_id}>
              <th scope="row">{place.name}</th>
              <td>{place.reports}</td>
              {BUCKETS.map((b) => (
                <td key={b}>{place.by_status[b]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MapPage({ mapStyleUrl }: { mapStyleUrl?: string }) {
  const incidentId = useParams().incidentId ?? "";
  const api = useApi();
  const [state, reload] = useLoad(incidentId, () => getIncidentMap(api, incidentId));

  useEffect(() => rememberIncident(incidentId), [incidentId]);

  return (
    <section className="page">
      <h1>Map</h1>
      <p className="muted">Incident {incidentId}</p>
      {state.status === "loading" && <p className="muted">Loading places</p>}
      {state.status === "error" && (
        <ErrorNotice error={state.error} notFound="This incident does not exist." onRetry={reload} />
      )}
      {state.status === "ready" && (
        <>
          <p className="flag" role="note">
            {state.data.caveat}
          </p>
          <p className="muted">
            {state.data.located_reports} reports with a place, {state.data.unlocated_reports} without.
            Counts as of {formatTime(state.data.updated_at)}; they refresh every 30 seconds.{" "}
            <button type="button" className="link" onClick={reload}>
              Refresh
            </button>
          </p>
          {mapStyleUrl ? (
            state.data.places.length > 0 && (
              <Suspense fallback={<p className="muted">Loading map</p>}>
                <PlacesMap places={state.data.places} styleUrl={mapStyleUrl} />
              </Suspense>
            )
          ) : (
            <p className="hint">The basemap is not set up here, so places are listed below.</p>
          )}
          <PlacesTable data={state.data} />
        </>
      )}
    </section>
  );
}
