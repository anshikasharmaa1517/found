import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useApi } from "../api/context";
import { getIncident } from "../api/incidents";
import { listPeople } from "../api/people";
import { ActivityRail } from "../components/ActivityRail";
import { DemoStory } from "../components/DemoStory";
import { ErrorNotice } from "../components/ErrorNotice";
import { GraphView } from "../components/GraphView";
import { IncidentMap } from "../components/IncidentMap";
import { SkeletonRows } from "../components/ui";
import { rememberIncident } from "../incident";
import { formatTime } from "../labels";
import { useLoad } from "../useLoad";

type Tab = "map" | "people" | "graph";

const TAB_LABELS: Record<Tab, string> = { map: "Map", people: "People", graph: "Graph" };

function PeoplePreview({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const [people, retry] = useLoad(`preview|${incidentId}`, () =>
    listPeople(api, incidentId, { limit: 12 }),
  );
  if (people.status === "loading") return <SkeletonRows label="Loading people" rows={6} />;
  if (people.status === "error") return <ErrorNotice error={people.error} onRetry={retry} />;
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col" className="num">
                Age
              </th>
            </tr>
          </thead>
          <tbody>
            {people.data.people.map((p) => (
              <tr key={p.id}>
                <th scope="row">
                  <Link to={`/people/${encodeURIComponent(p.id)}`}>{p.name}</Link>
                </th>
                <td className="num">
                  {p.age === null ? <span className="muted">Not reported</span> : p.age}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="meta">
        <Link to={`/incidents/${encodeURIComponent(incidentId)}/people`}>
          Search everyone reported
        </Link>
      </p>
    </>
  );
}

/** One incident at a glance: where it is, the demo story, the map and what is new. */
export function IncidentPage({ mapStyleUrl }: { mapStyleUrl?: string }) {
  const incidentId = useParams().incidentId ?? "";
  const api = useApi();
  const [incident, retry] = useLoad(`incident|${incidentId}`, () => getIncident(api, incidentId));
  const [tab, setTab] = useState<Tab>("map");

  useEffect(() => rememberIncident(incidentId), [incidentId]);

  if (incident.status === "loading") {
    return (
      <section className="page">
        <div className="skeleton-title skeleton-bar" aria-hidden="true" />
        <SkeletonRows label="Loading the incident" rows={3} />
      </section>
    );
  }
  if (incident.status === "error") {
    return (
      <section className="page">
        <ErrorNotice error={incident.error} notFound="This incident does not exist." onRetry={retry} />
      </section>
    );
  }

  const info = incident.data;
  return (
    <section className="page overview">
      <header className="incident-head">
        <p className="eyebrow">Current incident</p>
        <h1>{info.name}</h1>
        <p className="meta">
          {info.area}
          {info.started_at && <span className="meta-sep">Since {formatTime(info.started_at)}</span>}
          <span className="meta-sep mono">{info.id}</span>
        </p>
      </header>

      {info.is_demo && <DemoStory incidentId={incidentId} />}

      <div className="overview-grid">
        <div className="overview-main">
          <div className="segmented tabs" role="tablist" aria-label="Incident views">
            {(["map", "people", "graph"] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                id={`tab-${t}`}
                aria-selected={tab === t}
                aria-controls={`panel-${t}`}
                className={tab === t ? "chip active" : "chip"}
                onClick={() => setTab(t)}
              >
                {TAB_LABELS[t]}
              </button>
            ))}
          </div>
          <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
            {tab === "map" ? (
              <>
                <p className="meta">Tap a pin to see who reported what there, and when.</p>
                <IncidentMap incidentId={incidentId} mapStyleUrl={mapStyleUrl} />
              </>
            ) : tab === "people" ? (
              <PeoplePreview incidentId={incidentId} />
            ) : (
              <GraphView incidentId={incidentId} />
            )}
          </div>
        </div>
        <ActivityRail incidentId={incidentId} />
      </div>
    </section>
  );
}
