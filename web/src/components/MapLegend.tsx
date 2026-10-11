/** Open by default where there is room; on phones it starts folded so the map shows. */
function startsOpen(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
  return window.matchMedia("(min-width: 768px)").matches;
}

/** What the pins mean. Sits over the map and folds away. */
export function MapLegend({ river }: { river?: string | null }) {
  return (
    <details className="map-legend" open={startsOpen()}>
      <summary>Legend</summary>
      <ul>
        {river && (
          <li>
            <span className="legend-river" aria-hidden="true" />
            {river} that flooded (its course, not the flood&apos;s extent)
          </li>
        )}
        <li>
          <span className="legend-pin" aria-hidden="true" />
          Reports about people at a place
        </li>
        <li>
          <span className="legend-pin legend-review" aria-hidden="true" />
          Some reports there need a reviewer
        </li>
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
      <p>Places are as reported, not verified. Counts are reports, not people.</p>
    </details>
  );
}
