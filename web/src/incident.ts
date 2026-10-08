/** The incident the user last opened, kept per browser for convenience only. */

const KEY = "found.incidentId";
const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export function isIncidentId(value: string): boolean {
  return ID_PATTERN.test(value);
}

export function rememberedIncident(fallback?: string): string | null {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored && isIncidentId(stored)) return stored;
  } catch {
    // Storage can be blocked; the fallback still works.
  }
  return fallback && isIncidentId(fallback) ? fallback : null;
}

export function rememberIncident(incidentId: string): void {
  try {
    localStorage.setItem(KEY, incidentId);
  } catch {
    // Not remembering is fine.
  }
}
