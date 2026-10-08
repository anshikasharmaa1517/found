import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { useApi } from "../api/context";
import { useUser } from "../auth/context";
import { displayName, ROLE_LABELS, type Role } from "../auth/user";
import { isIncidentId, rememberedIncident } from "../incident";

const ROLE_TASKS: Record<Role, string> = {
  publisher: "Publish structured reports as your organization.",
  reviewer: "Review conflicts, trace where reports came from, and decide matches.",
  family: "Follow people and get alerts when new reports arrive.",
  admin: "Manage incidents and the demo.",
};

type Health = "checking" | "up" | "down";

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

  return (
    <section className="page">
      <h1>Welcome, {displayName(user)}</h1>
      <ul className="roles">
        {user.roles.map((role) => (
          <li key={role}>
            <strong>{ROLE_LABELS[role]}</strong>: {ROLE_TASKS[role]}
          </li>
        ))}
      </ul>
      {user.orgId && <p className="muted">Organization: {user.orgId}</p>}
      <form className="search" onSubmit={openIncident}>
        <label>
          Incident
          <input
            name="incident"
            defaultValue={rememberedIncident(defaultIncidentId) ?? ""}
            aria-invalid={incidentError ? "true" : undefined}
            required
          />
        </label>
        <button type="submit">Open people</button>
      </form>
      {incidentError && (
        <p className="error" role="alert">
          {incidentError}
        </p>
      )}
      <p className="status" role="status">
        Service:{" "}
        {health === "checking" ? "checking" : health === "up" ? "available" : "not reachable"}
      </p>
    </section>
  );
}
