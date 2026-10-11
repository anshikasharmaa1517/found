/** Admin actions (design Section 7.3). */

import type { ApiClient } from "./client";

/** Reloads a demo incident from its dataset. It runs in the background. */
export function resetDemo(
  api: ApiClient,
  incidentId: string,
): Promise<{ incident_id: string; status: "RESETTING" }> {
  return api.post(`/v1/admin/incidents/${encodeURIComponent(incidentId)}/reset`);
}
