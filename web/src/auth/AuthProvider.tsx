import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { AuthContext, type AuthContextValue, type AuthState } from "./context";
import type { AuthGateway, SignInStep } from "./gateway";

export function AuthProvider({ gateway, children }: { gateway: AuthGateway; children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const loadUser = useCallback(async () => {
    const user = await gateway.currentUser();
    setState(user ? { status: "signedIn", user } : { status: "signedOut" });
  }, [gateway]);

  useEffect(() => {
    let active = true;
    gateway
      .currentUser()
      .catch(() => null)
      .then((user) => {
        if (active) setState(user ? { status: "signedIn", user } : { status: "signedOut" });
      });
    return () => {
      active = false;
    };
  }, [gateway]);

  // Stable, so API clients built from it are not recreated on every state change.
  const idToken = useCallback(() => gateway.idToken(), [gateway]);

  const settle = useCallback(
    async (step: SignInStep) => {
      if (step.kind === "done") await loadUser();
      else if (step.kind === "newPassword" || step.kind === "totp")
        setState({ status: "challenge", challenge: step.kind });
      return step;
    },
    [loadUser],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      state,
      signIn: async (email, password) => settle(await gateway.signIn(email, password)),
      respond: async (answer) => settle(await gateway.respond(answer)),
      signOut: async () => {
        await gateway.signOut();
        setState({ status: "signedOut" });
      },
      idToken,
    }),
    [gateway, idToken, settle, state],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
