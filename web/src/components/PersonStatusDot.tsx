import type { PersonStatus } from "../api/people";

const TONE: Record<string, string> = {
  MISSING: "bad",
  FOUND_SAFE: "ok",
  INJURED: "warn",
};

/** A person's cited status as a dot and a label. Color is never the only signal. */
export function PersonStatusDot({ status }: { status: PersonStatus | null | undefined }) {
  if (!status) return null;
  const tone = status.withheld ? "" : (TONE[status.claim_type ?? ""] ?? "");
  return (
    <span className={`status-dot ${tone}`}>
      {status.label}
      {status.needs_review && <span className="meta-sep">needs review</span>}
    </span>
  );
}
