import { useMemo, type ReactNode } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";

import { createApiClient } from "./api/client";
import { ApiContext } from "./api/context";
import { AuthProvider } from "./auth/AuthProvider";
import { useAuth } from "./auth/context";
import type { AuthGateway } from "./auth/gateway";
import { RequireAuth } from "./auth/RequireAuth";
import { AppShell } from "./components/AppShell";
import type { SocketLike } from "./live/client";
import { AlertsPage } from "./pages/AlertsPage";
import { HomePage } from "./pages/HomePage";
import { IntakePage } from "./pages/IntakePage";
import { InvestigationPage } from "./pages/InvestigationPage";
import { MapPage } from "./pages/MapPage";
import { PeoplePage } from "./pages/PeoplePage";
import { PersonPage } from "./pages/PersonPage";
import { ReportPage } from "./pages/ReportPage";
import { ReviewPage } from "./pages/ReviewPage";
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
  wsUrl?: string;
  /** Tests pass a fake socket. */
  createSocket?: (url: string) => SocketLike;
}

export function AppRoutes({
  defaultIncidentId,
  mapStyleUrl,
  wsUrl,
  createSocket,
}: AppSettings = {}) {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignInPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell wsUrl={wsUrl} createSocket={createSocket} />
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
        <Route
          path="incidents/:incidentId/upload"
          element={
            <RequireAuth roles={["publisher"]}>
              <IntakePage />
            </RequireAuth>
          }
        />
        <Route
          path="incidents/:incidentId/review"
          element={
            <RequireAuth roles={["reviewer", "admin"]}>
              <ReviewPage />
            </RequireAuth>
          }
        />
        <Route
          path="investigations/:investigationId"
          element={
            <RequireAuth roles={["reviewer", "admin"]}>
              <InvestigationPage />
            </RequireAuth>
          }
        />
        <Route
          path="alerts"
          element={
            <RequireAuth roles={["family"]}>
              <AlertsPage />
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
  wsUrl,
}: AppSettings & {
  gateway: AuthGateway;
  apiUrl: string;
}) {
  return (
    <AuthProvider gateway={gateway}>
      <WithApi apiUrl={apiUrl}>
        <BrowserRouter>
          <AppRoutes
            defaultIncidentId={defaultIncidentId}
            mapStyleUrl={mapStyleUrl}
            wsUrl={wsUrl}
          />
        </BrowserRouter>
      </WithApi>
    </AuthProvider>
  );
}
