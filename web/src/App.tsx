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
import { MapPage } from "./pages/MapPage";
import { PeoplePage } from "./pages/PeoplePage";
import { PersonPage } from "./pages/PersonPage";
import { ReportPage } from "./pages/ReportPage";
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

export interface AppSettings {
  defaultIncidentId?: string;
  mapStyleUrl?: string;
}

export function AppRoutes({ defaultIncidentId, mapStyleUrl }: AppSettings = {}) {
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
        <Route path="incidents/:incidentId/map" element={<MapPage mapStyleUrl={mapStyleUrl} />} />
        <Route
          path="incidents/:incidentId/report"
          element={
            <RequireAuth roles={["publisher"]}>
              <ReportPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export function App({
  gateway,
  apiUrl,
  defaultIncidentId,
  mapStyleUrl,
}: AppSettings & {
  gateway: AuthGateway;
  apiUrl: string;
}) {
  return (
    <AuthProvider gateway={gateway}>
      <WithApi apiUrl={apiUrl}>
        <BrowserRouter>
          <AppRoutes defaultIncidentId={defaultIncidentId} mapStyleUrl={mapStyleUrl} />
        </BrowserRouter>
      </WithApi>
    </AuthProvider>
  );
}
