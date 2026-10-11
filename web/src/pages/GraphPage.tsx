import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { GraphView } from "../components/GraphView";
import { PageHeader } from "../components/ui";
import { rememberIncident } from "../incident";

/** Every stored record in the incident and the typed links between them. */
export function GraphPage() {
  const incidentId = useParams().incidentId ?? "";
  useEffect(() => rememberIncident(incidentId), [incidentId]);
  return (
    <section className="page">
      <PageHeader
        title="Graph"
        description="The stored records behind every other tab, and the typed links between them."
      />
      <GraphView incidentId={incidentId} />
    </section>
  );
}
