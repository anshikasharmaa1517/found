import type { MapContext } from "../api/incidents";
import { PLACE_STATUS_LABELS, type PlaceStatus } from "../api/map";
import { ChevronIcon } from "./icons";

/** Open by default where there is room; on phones it starts folded so the map shows. */
function startsOpen(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
  return window.matchMedia("(min-width: 768px)").matches;
}

// Read across, two to a row: the urgent statuses first.
const STATUS_ORDER: PlaceStatus[] = ["MISSING", "NEEDS_REVIEW", "FOUND_SAFE", "NONE"];

/** "Trishuli river" reads as "Trishuli" after "Flooded river:". */
function riverLabel(name: string): string {
  return name.replace(/\s+river$/i, "");
}

/** What the map shows. Sits over the map and folds away. */
export function MapLegend({
  river,
  context = null,
  conditions = false,
}: {
  river?: string | null;
  context?: MapContext | null;
  /** Roads, shelters or hazards are on the map too. */
  conditions?: boolean;
}) {
  return (
    <details className="map-legend" open={startsOpen()}>
      <summary>
        Legend
        <ChevronIcon size={16} />
      </summary>
      <ul className="legend-statuses">
        {STATUS_ORDER.map((status) => (
          <li key={status}>
            <span className={`legend-dot legend-${status.toLowerCase()}`} aria-hidden="true" />
            {PLACE_STATUS_LABELS[status]}
          </li>
        ))}
      </ul>
      <p className="legend-heat">
        Fewer reports
        <span className="heat-step heat-low" aria-hidden="true" />
        <span className="heat-step heat-mid" aria-hidden="true" />
        <span className="heat-step heat-high" aria-hidden="true" />
        More
      </p>
      <ul>
        {river && (
          <li>
            <span className="legend-line legend-flood" aria-hidden="true" />
            Flooded river: {riverLabel(river)}
          </li>
        )}
        {context && context.rivers.length > 0 && (
          <li>
            <span className="legend-line legend-other-river" aria-hidden="true" />
            Other rivers
          </li>
        )}
        {context?.district && (
          <li>
            <span className="legend-line legend-district" aria-hidden="true" />
            {context.district.name ?? "District"}
          </li>
        )}
      </ul>
      {conditions && (
        <ul className="legend-conditions">
          <li>
            <span className="legend-square" aria-hidden="true">
              R
            </span>
            Road or bridge
          </li>
          <li>
            <span className="legend-square" aria-hidden="true">
              S
            </span>
            Shelter, <span className="legend-letter">A</span> aid point,{" "}
            <span className="legend-letter">H</span> hazard
          </li>
          <li>
            <span className="legend-square legend-disputed" aria-hidden="true" />
            Sources disagree
          </li>
        </ul>
      )}
      <p className="legend-note">
        Places are as reported, not verified. Counts are reports, not people.
      </p>
    </details>
  );
}
