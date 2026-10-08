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
