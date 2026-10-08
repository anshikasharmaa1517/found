import { useState } from "react";
import { useNavigate } from "react-router-dom";

import type { ApiError } from "../api/client";
import { useApi } from "../api/context";
import { startInvestigation } from "../api/investigations";
import { asApiError } from "../useLoad";

/** Why a start was refused, in words; the API codes are in design Section 7.3. */
function refusal(error: ApiError): string {
  switch (error.code) {
    case "LIVE_UNAVAILABLE":
      return "Live investigations are switched off right now.";
    case "BUDGET_LIMIT":
      return "This month's investigation budget is used up.";
    case "FORBIDDEN":
      return "Only reviewers can start investigations.";
    case "NOT_FOUND":
      return "This report was not found.";
    default:
      return "The investigation could not be started. Try again.";
  }
}

/** Starts (or reuses) an investigation of one report and opens it. */
export function TraceButton({ claimId }: { claimId: string }) {
  const api = useApi();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    setBusy(true);
    setError(null);
    try {
      const result = await startInvestigation(api, claimId);
      const served = result.mode === "CACHED" ? "?served=cached" : "";
      navigate(`/investigations/${encodeURIComponent(result.investigation_id)}${served}`);
    } catch (err) {
      const apiError = asApiError(err);
      const running = apiError.details.investigation_id;
      // One run per report at a time: open the one already running.
      if (apiError.code === "IN_PROGRESS" && typeof running === "string") {
        navigate(`/investigations/${encodeURIComponent(running)}`);
        return;
      }
      setError(refusal(apiError));
      setBusy(false);
    }
  }

  return (
    <div className="trace">
      <button type="button" className="link" onClick={onClick} disabled={busy}>
        {busy ? "Starting" : "Trace where this came from"}
      </button>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
