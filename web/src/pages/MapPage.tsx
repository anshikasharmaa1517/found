import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import {
  CLIMATE_TYPE_LABELS,
  CLIMATE_TYPES,
  getClimateLayer,
  type ClimateFeature,
  type ClimateType,
} from "../api/climate";
import { useApi } from "../api/context";
import { BUCKET_LABELS, BUCKETS, getIncidentMap, type IncidentMap } from "../api/map";
import { ErrorNotice } from "../components/ErrorNotice";
import { PageHeader, SkeletonRows } from "../components/ui";
import { rememberIncident } from "../incident";
import { claimTypeLabel, formatTime } from "../labels";
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
            <th scope="col" className="num">
              Reports
            </th>
            {BUCKETS.map((b) => (
              <th scope="col" className="num" key={b}>
                {BUCKET_LABELS[b]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.places.map((place) => (
            <tr key={place.location_id}>
              <th scope="row">{place.name}</th>
              <td className="num">{place.reports}</td>
              {BUCKETS.map((b) => (
                <td className="num" key={b}>
                  {place.by_status[b]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The conditions as a list: always shown, so the picture works without the map. */
function Conditions({ features }: { features: ClimateFeature[] }) {
  if (features.length === 0) {
    return <p className="empty">No reports about roads, shelters or hazards yet.</p>;
  }
  return (
    <ul className="conditions">
      {features.map((f) => (
        <li key={f.subject_id} className="condition">
          <div className="entry-head">
            <strong>{f.name}</strong>
            <span className="tag">{CLIMATE_TYPE_LABELS[f.subject_type]}</span>
            {f.conflicts.length > 0 && <span className="status-dot warn">Sources disagree</span>}
          </div>
          <p>
            {f.label}. <span className="meta">{f.basis}.</span>
          </p>
          {f.conflicts.length > 0 && (
            <ul>
              {f.conflicts.map((c) => (
                <li key={c.claim_id}>
                  {c.source} says {claimTypeLabel(c.claim_type)}, {formatTime(c.reported_at)}
                </li>
              ))}
            </ul>
          )}
          <p className="meta">
            {f.location ? f.location.name : "No place given"}. {f.report_count} report
            {f.report_count === 1 ? "" : "s"}.
          </p>
        </li>
      ))}
    </ul>
  );
}

type Layer = "PEOPLE" | ClimateType;

export function MapPage({ mapStyleUrl }: { mapStyleUrl?: string }) {
  const incidentId = useParams().incidentId ?? "";
  const api = useApi();
  const [state, reload] = useLoad(incidentId, () => getIncidentMap(api, incidentId));
  const [climate, reloadClimate] = useLoad(`climate|${incidentId}`, () =>
    getClimateLayer(api, incidentId),
  );
  const [hidden, setHidden] = useState<Set<Layer>>(new Set());
  const features = useMemo(
    () =>
      climate.status === "ready"
        ? climate.data.features.filter((f) => !hidden.has(f.subject_type))
        : [],
    [climate, hidden],
  );
  const present = climate.status === "ready"
    ? CLIMATE_TYPES.filter((t) => climate.data.features.some((f) => f.subject_type === t))
    : [];

  function toggle(layer: Layer) {
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(layer)) next.delete(layer);
      else next.add(layer);
      return next;
    });
  }

  function refresh() {
    reload();
    reloadClimate();
  }

  useEffect(() => rememberIncident(incidentId), [incidentId]);

  return (
    <section className="page">
      <PageHeader
        title="Map"
        description="Where reports say people were, and the state of roads, shelters and hazards."
      />
      {state.status === "loading" && <SkeletonRows label="Loading places" rows={4} />}
      {state.status === "error" && (
        <ErrorNotice error={state.error} notFound="This incident does not exist." onRetry={reload} />
      )}
      {state.status === "ready" && (
        <>
          <p className="notice-box" role="note">
            {state.data.caveat}
          </p>
          <p className="meta">
            {state.data.located_reports} reports with a place, {state.data.unlocated_reports} without.
            Counts as of {formatTime(state.data.updated_at)}; they refresh every 30 seconds.{" "}
            <button type="button" className="link" onClick={refresh}>
              Refresh
            </button>
          </p>
          <fieldset className="layers">
            <legend>Show on the map</legend>
            {(["PEOPLE", ...present] as Layer[]).map((layer) => (
              <label key={layer} className="inline">
                <input
                  type="checkbox"
                  checked={!hidden.has(layer)}
                  onChange={() => toggle(layer)}
                />
                {layer === "PEOPLE" ? "Reports about people" : CLIMATE_TYPE_LABELS[layer]}
              </label>
            ))}
          </fieldset>
          {mapStyleUrl ? (
            (state.data.places.length > 0 || features.length > 0) && (
              <Suspense fallback={<p className="muted">Loading map</p>}>
                <PlacesMap
                  places={hidden.has("PEOPLE") ? [] : state.data.places}
                  features={features}
                  styleUrl={mapStyleUrl}
                />
              </Suspense>
            )
          ) : (
            <p className="hint">The basemap is not set up here, so places are listed below.</p>
          )}
          <PlacesTable data={state.data} />
          <h2>Roads, shelters and hazards</h2>
          {climate.status === "loading" && <p className="muted">Loading conditions</p>}
          {climate.status === "error" && (
            <ErrorNotice error={climate.error} onRetry={reloadClimate} />
          )}
          {climate.status === "ready" && (
            <>
              <p className="notice-box" role="note">
                {climate.data.caveat}
              </p>
              <Conditions features={features} />
            </>
          )}
        </>
      )}
    </section>
  );
}
