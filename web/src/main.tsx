import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { mapStyleUrl } from "./api/map";
import { cognitoGateway } from "./auth/cognito";
import { readConfig } from "./config";
import "./styles.css";

const root = createRoot(document.getElementById("root")!);
const result = readConfig(import.meta.env);

if (result.ok) {
  const { config } = result;
  const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  root.render(
    <StrictMode>
      <App
        gateway={cognitoGateway(result.config)}
        apiUrl={result.config.apiUrl}
        defaultIncidentId={result.config.defaultIncidentId}
        mapStyleUrl={
          config.mapApiKey ? mapStyleUrl(config.region, config.mapApiKey, dark) : undefined
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
