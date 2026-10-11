import { useState } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/context";
import { getTimeline, type VisibleEntry } from "../api/people";
import { claimTypeLabel } from "../labels";
import { useLiveMessage } from "../live/context";
import { useLoad } from "../useLoad";
import { BellIcon, CloseIcon } from "./icons";

const STATUS_TYPES = new Set(["MISSING", "FOUND_SAFE", "INJURED", "DECEASED"]);
const KEPT_MAX = 4;

interface Fresh {
  alertId: string;
  subjectId: string;
  message: string;
}

function statusTone(claimType: string | undefined): string {
  if (claimType === "FOUND_SAFE") return "ok";
  if (claimType === "MISSING") return "bad";
  if (claimType === "INJURED") return "warn";
  return "neutral";
}

/** The reports kept on the person's record, newest first, so nothing looks replaced. */
function Kept({ fresh }: { fresh: Fresh }) {
  const api = useApi();
  const [timeline] = useLoad(`banner|${fresh.alertId}`, () =>
    getTimeline(api, fresh.subjectId, { order: "desc", limit: 10 }),
  );
  if (timeline.status !== "ready") return null;
  const kept = timeline.data.entries
    .filter((e): e is VisibleEntry => !e.withheld && STATUS_TYPES.has(e.claim_type))
    .slice(1, 1 + KEPT_MAX);
  if (kept.length === 0) return null;
  return (
    <p className="banner-kept">
      <span className="meta">Still on record, not overwritten:</span>
      {kept.map((e) => (
        <span key={e.claim_id} className={`pill ${statusTone(e.claim_type)}`}>
          {e.source} · {claimTypeLabel(e.claim_type)}
        </span>
      ))}
    </p>
  );
}

function Banner({ fresh, onDismiss }: { fresh: Fresh; onDismiss: () => void }) {
  const api = useApi();
  const [timeline] = useLoad(`banner-head|${fresh.alertId}`, () =>
    getTimeline(api, fresh.subjectId, { order: "desc", limit: 1 }),
  );
  const ready = timeline.status === "ready" ? timeline.data : null;
  const newest = ready?.entries.find((e): e is VisibleEntry => !e.withheld);
  const tone = statusTone(newest?.claim_type);
  return (
    <section className={`alert-banner ${tone}`} role="status" aria-live="polite" aria-label="New alert">
      <span className="banner-icon" aria-hidden="true">
        <span className="banner-ping" />
        <BellIcon size={20} />
      </span>
      <div className="banner-text">
        <p className="eyebrow">
          {ready ? `New report about ${ready.person.name}` : "New report about someone you follow"}
        </p>
        <h2>{fresh.message}</h2>
        <Kept fresh={fresh} />
      </div>
      <div className="banner-actions">
        <Link className="button-link large" to={`/people/${encodeURIComponent(fresh.subjectId)}`}>
          See every report
        </Link>
        <button type="button" className="icon-button ghost" aria-label="Dismiss alert" onClick={onDismiss}>
          <CloseIcon />
        </button>
      </div>
    </section>
  );
}

/** A large banner for the newest alert, as it arrives. The alerts page keeps them all. */
export function AlertBanner() {
  const [fresh, setFresh] = useState<Fresh | null>(null);
  useLiveMessage((m) => {
    if (m.type === "alert.created") {
      setFresh({ alertId: m.alert_id, subjectId: m.subject_id, message: m.message });
    }
  });
  if (!fresh) return null;
  return <Banner key={fresh.alertId} fresh={fresh} onDismiss={() => setFresh(null)} />;
}
