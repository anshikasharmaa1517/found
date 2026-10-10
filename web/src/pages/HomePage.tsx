import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useApi } from "../api/context";
import { useUser } from "../auth/context";
import { displayName, hasRole, ROLE_LABELS, type Role, type User } from "../auth/user";
import { PageHeader } from "../components/ui";
import { isIncidentId, rememberedIncident } from "../incident";

const ROLE_TASKS: Record<Role, string> = {
  publisher: "Publish structured reports as your organization.",
  reviewer: "Review conflicts, trace where reports came from, and decide matches.",
  family: "Follow people and get alerts when new reports arrive.",
  admin: "Manage incidents and the demo.",
};

type Health = "checking" | "up" | "down";

interface Destination {
  to: string;
  title: string;
  text: string;
}

/** Where this account's work happens in the open incident, most important first. */
function destinations(user: User, incidentId: string): Destination[] {
  const base = `/incidents/${encodeURIComponent(incidentId)}`;
  const list: Destination[] = [];
  if (hasRole(user, "reviewer", "admin")) {
    list.push({
      to: `${base}/review`,
      title: "Review queue",
      text: "Conflicts, agent findings, possible duplicates and extracted reports waiting for a decision.",
    });
  }
  if (hasRole(user, "publisher")) {
    list.push(
      {
        to: `${base}/report`,
        title: "Publish a report",
        text: "Add one report as your organization. It is stored exactly as given.",
      },
      {
        to: `${base}/upload`,
        title: "Upload a report",
        text: "Send a scanned list or pasted text; a reviewer confirms each suggested report.",
      },
    );
  }
  if (hasRole(user, "family")) {
    list.push({
      to: "/alerts",
      title: "Alerts",
      text: "New reports about the people you follow.",
    });
  }
  list.push(
    {
      to: `${base}/people`,
      title: "People",
      text: "Everyone reported, each with a timeline that names every source.",
    },
    {
      to: `${base}/map`,
      title: "Map",
      text: "Reports per place, and roads, shelters and hazards as reported.",
    },
  );
  return list;
}

export function HomePage({ defaultIncidentId }: { defaultIncidentId?: string }) {
  const user = useUser();
  const api = useApi();
  const navigate = useNavigate();
  const [incidentError, setIncidentError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health>("checking");

  useEffect(() => {
    let active = true;
    api
      .get<{ status: string }>("/v1/health")
      .then((body) => active && setHealth(body.status === "ok" ? "up" : "down"))
      .catch(() => active && setHealth("down"));
    return () => {
      active = false;
    };
  }, [api]);

  function openIncident(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = String(new FormData(event.currentTarget).get("incident") ?? "").trim();
    if (!isIncidentId(id)) {
      setIncidentError("Enter an incident id, for example inc_01J9X0.");
      return;
    }
    navigate(`/incidents/${encodeURIComponent(id)}/people`);
  }

  const incidentId = rememberedIncident(defaultIncidentId);
  const tasks = user.roles.map((role) => `${ROLE_LABELS[role]}: ${ROLE_TASKS[role]}`).join(" ");

  return (
    <section className="page">
      <PageHeader title={`Welcome, ${displayName(user)}`} description={tasks} />

      {incidentId && (
        <>
          <h2 className="section-label">
            Incident <span className="mono">{incidentId}</span>
          </h2>
          <ul className="rows destinations">
            {destinations(user, incidentId).map((d) => (
              <li key={d.to}>
                <Link to={d.to}>{d.title}</Link>
                <p className="meta">{d.text}</p>
              </li>
            ))}
          </ul>
        </>
      )}

      <form className="search panel" onSubmit={openIncident}>
        <label>
          Incident
          <input
            name="incident"
            defaultValue={incidentId ?? ""}
            aria-invalid={incidentError ? "true" : undefined}
            required
          />
        </label>
        {/* With an incident open, the destinations above are the main way in. */}
        <button type="submit" className={incidentId ? "secondary" : undefined}>
          Open people
        </button>
      </form>
      {incidentError && (
        <p className="error" role="alert">
          {incidentError}
        </p>
      )}
      {user.orgId && <p className="meta">Organization: {user.orgId}</p>}
      <p className="status" role="status">
        <span className={`status-dot ${health === "up" ? "ok" : health === "down" ? "bad" : ""}`}>
          Service:{" "}
          {health === "checking" ? "checking" : health === "up" ? "available" : "not reachable"}
        </span>
      </p>
    </section>
  );
}
