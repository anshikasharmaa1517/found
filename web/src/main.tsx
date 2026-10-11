import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { mapStyleUrl } from "./api/map";
import { cognitoGateway } from "./auth/cognito";
import { readConfig } from "./config";
import { applyTheme, initialTheme } from "./theme";
import "./styles.css";

// Before the first paint, so a saved dark theme never flashes light.
applyTheme(initialTheme());

const root = createRoot(document.getElementById("root")!);
const result = readConfig(import.meta.env);

if (result.ok) {
  const { config } = result;
  root.render(
    <StrictMode>
      <App
        gateway={cognitoGateway(result.config)}
        apiUrl={result.config.apiUrl}
        defaultIncidentId={result.config.defaultIncidentId}
        wsUrl={config.wsUrl}
        mapStyleUrl={config.mapApiKey ? mapStyleUrl(config.region, config.mapApiKey) : undefined}
        darkMapStyleUrl={
          config.mapApiKey ? mapStyleUrl(config.region, config.mapApiKey, true) : undefined
        }
      />
    </StrictMode>,
  );
} else {
  root.render(
    <main className="sign-in">
      <section className="card" role="alert">
        <h1>Setup needed</h1>
        <p>These settings are missing: {result.missing.join(", ")}.</p>
        <p className="hint">Copy .env.example to .env.local and fill in the stack outputs.</p>
      </section>
    </main>,
  );
}
