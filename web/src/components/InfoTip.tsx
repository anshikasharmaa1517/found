import { InfoIcon } from "./icons";

/**
 * A small (i) that opens a caveat, as in Trace: details one click away instead of always
 * on screen. A native <details>, so it works with the keyboard and screen readers.
 */
export function InfoTip({ label, children }: { label: string; children: string }) {
  return (
    <details className="info-tip">
      <summary aria-label={label} title={label}>
        <InfoIcon />
      </summary>
      <p>{children}</p>
    </details>
  );
}
