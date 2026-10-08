import { useMemo, type ReactNode } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";

import { createApiClient } from "./api/client";
import { ApiContext } from "./api/context";
import { AuthProvider } from "./auth/AuthProvider";
import { useAuth } from "./auth/context";
import type { AuthGateway } from "./auth/gateway";
import { RequireAuth } from "./auth/RequireAuth";
import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/HomePage";
import { PeoplePage } from "./pages/PeoplePage";
import { PersonPage } from "./pages/PersonPage";
import { SignInPage } from "./pages/SignInPage";

function NotFound() {
  return (
    <section className="page">
      <h1>Page not found</h1>
      <p>
        <Link to="/">Go to the home page</Link>
      </p>
    </section>
  );
}

function WithApi({ apiUrl, children }: { apiUrl: string; children: ReactNode }) {
  const { idToken } = useAuth();
  const client = useMemo(() => createApiClient({ baseUrl: apiUrl, idToken }), [apiUrl, idToken]);
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

export function AppRoutes({ defaultIncidentId }: { defaultIncidentId?: string } = {}) {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignInPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage defaultIncidentId={defaultIncidentId} />} />
        <Route path="incidents/:incidentId/people" element={<PeoplePage />} />
        <Route path="people/:personId" element={<PersonPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export function App({
  gateway,
  apiUrl,
  defaultIncidentId,
}: {
  gateway: AuthGateway;
  apiUrl: string;
  defaultIncidentId?: string;
}) {
  return (
    <AuthProvider gateway={gateway}>
      <WithApi apiUrl={apiUrl}>
        <BrowserRouter>
          <AppRoutes defaultIncidentId={defaultIncidentId} />
        </BrowserRouter>
      </WithApi>
    </AuthProvider>
  );
}
