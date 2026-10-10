/** The signed-in user, read from the Cognito ID token. The API checks roles again. */

export type Role = "admin" | "reviewer" | "publisher" | "family";

// Same order as the Cognito group precedence: the first match is the main role.
export const ROLES: readonly Role[] = ["admin", "reviewer", "publisher", "family"];

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Admin",
  reviewer: "Reviewer",
  publisher: "Publisher",
  family: "Family",
};

export interface User {
  id: string;
  email: string | null;
  name: string | null;
  roles: Role[];
  orgId: string | null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

export function userFromClaims(claims: Record<string, unknown>): User {
  const raw = claims["cognito:groups"];
  const groups = Array.isArray(raw) ? raw.filter((g): g is string => typeof g === "string") : [];
  return {
    id: text(claims.sub) ?? "",
    email: text(claims.email),
    name: text(claims.name),
    roles: ROLES.filter((role) => groups.includes(role)),
    orgId: text(claims["custom:org_id"]),
  };
}

export function hasRole(user: User, ...roles: Role[]): boolean {
  return roles.some((role) => user.roles.includes(role));
}

export function mainRole(user: User): Role | null {
  return user.roles[0] ?? null;
}

export function displayName(user: User): string {
  return user.name ?? user.email ?? "Signed in";
}

/** Two letters for the account button: first and last initial, or the first two letters. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1] ?? "") : "";
  const letters = last ? `${first.charAt(0)}${last.charAt(0)}` : first.slice(0, 2);
  return letters.toUpperCase();
}
