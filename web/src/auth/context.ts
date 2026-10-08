import { createContext, useContext } from "react";

import type { SignInStep } from "./gateway";
import type { User } from "./user";

export type AuthState =
  | { status: "loading" }
  | { status: "signedOut" }
  | { status: "challenge"; challenge: "newPassword" | "totp" }
  | { status: "signedIn"; user: User };

export interface AuthContextValue {
  state: AuthState;
  signIn(email: string, password: string): Promise<SignInStep>;
  respond(answer: string): Promise<SignInStep>;
  signOut(): Promise<void>;
  /** A fresh ID token for API calls, or null when signed out. */
  idToken(): Promise<string | null>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

/** The signed-in user. Only for components rendered behind RequireAuth. */
export function useUser(): User {
  const { state } = useAuth();
  if (state.status !== "signedIn") throw new Error("useUser needs a signed-in user");
  return state.user;
}
