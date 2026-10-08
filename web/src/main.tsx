import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { cognitoGateway } from "./auth/cognito";
import { readConfig } from "./config";
import "./styles.css";

const root = createRoot(document.getElementById("root")!);
const result = readConfig(import.meta.env);

if (result.ok) {
  root.render(
    <StrictMode>
      <App
        gateway={cognitoGateway(result.config)}
        apiUrl={result.config.apiUrl}
        defaultIncidentId={result.config.defaultIncidentId}
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
