import { useEffect, useState } from "react";

import { useApi } from "../api/context";
import { useUser } from "../auth/context";
import { displayName, ROLE_LABELS, type Role } from "../auth/user";

const ROLE_TASKS: Record<Role, string> = {
  publisher: "Publish structured reports as your organization.",
  reviewer: "Review conflicts, trace where reports came from, and decide matches.",
  family: "Follow people and get alerts when new reports arrive.",
  admin: "Manage incidents and the demo.",
};

type Health = "checking" | "up" | "down";

export function HomePage() {
  const user = useUser();
  const api = useApi();
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
      <p className="status" role="status">
        Service:{" "}
        {health === "checking" ? "checking" : health === "up" ? "available" : "not reachable"}
      </p>
    </section>
  );
}
