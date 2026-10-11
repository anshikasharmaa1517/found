import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/context";
import {
  EDGE_LABELS,
  getIncidentGraph,
  NODE_LABELS,
  NODE_NAME,
  type EdgeKind,
  type GraphNode,
  type IncidentGraph,
  type NodeKind,
} from "../api/graph";
import { layout, neighbourhood } from "../graphLayout";
import { useLoad } from "../useLoad";
import { ErrorNotice } from "./ErrorNotice";
import { SkeletonRows } from "./ui";

const WIDTH = 1000;
const HEIGHT = 620;
const OPTIONAL: NodeKind[] = ["report", "source", "place", "subject", "investigation"];
const ALWAYS_LABELLED: NodeKind[] = ["person", "subject", "source", "place"];
const LEGEND_EDGES: EdgeKind[] = ["about", "from", "mentions", "relays", "possibly_same", "same_person"];

function Shape({ node, size }: { node: GraphNode; size: number }) {
  switch (node.kind) {
    case "person":
      return <circle r={size} className="g-person" />;
    case "subject":
      return <rect x={-size} y={-size} width={size * 2} height={size * 2} rx={2} className="g-subject" />;
    case "report":
      return <circle r={size * 0.45} className="g-report" />;
    case "source":
      return <rect x={-size} y={-size} width={size * 2} height={size * 2} transform="rotate(45)" className="g-source" />;
    case "place":
      return <circle r={size * 0.8} className="g-place" />;
    default:
      return <rect x={-size} y={-size} width={size * 2} height={size * 2} rx={3} className="g-investigation" />;
  }
}

function Details({
  node,
  graph,
}: {
  node: GraphNode;
  graph: IncidentGraph;
}) {
  const subjectOf = graph.edges.find((e) => e.source === node.id && e.kind === "about")?.target;
  const links = graph.edges.filter((e) => e.source === node.id || e.target === node.id).length;
  let to: string | null = null;
  if (node.kind === "person") to = `/people/${encodeURIComponent(node.id)}`;
  if (node.kind === "investigation") to = `/investigations/${encodeURIComponent(node.id)}`;
  if (node.kind === "report" && subjectOf && graph.nodes.find((n) => n.id === subjectOf)?.kind === "person") {
    to = `/people/${encodeURIComponent(subjectOf)}#entry-${node.id}`;
  }
  return (
    <div className="graph-details" aria-live="polite">
      <p className="eyebrow">{NODE_NAME[node.kind]}</p>
      <strong>{node.label}</strong>
      {node.detail && <p className="meta">{node.detail}</p>}
      <p className="meta">
        {links} link{links === 1 ? "" : "s"}
        <span className="meta-sep mono">{node.id}</span>
      </p>
      {to && <Link to={to}>Open</Link>}
    </div>
  );
}

/** Every stored record of the incident and the typed links between them. */
export function GraphView({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const [state, retry] = useLoad(`graph|${incidentId}`, () => getIncidentGraph(api, incidentId));
  const [hidden, setHidden] = useState<Set<NodeKind>>(new Set());
  const [focus, setFocus] = useState<string | null | undefined>(undefined);
  const [selected, setSelected] = useState<string | null>(null);

  const graph = state.status === "ready" ? state.data : null;
  const people = useMemo(
    () => (graph ? graph.nodes.filter((n) => n.kind === "person").sort((a, b) => a.label.localeCompare(b.label)) : []),
    [graph],
  );
  // The demo opens on Maya, the person its story follows; elsewhere, everything.
  const centre =
    focus === undefined ? (people.find((p) => p.label === "Maya Rawat")?.id ?? null) : focus;

  const view = useMemo(() => {
    if (!graph) return null;
    let nodes = graph.nodes.filter((n) => !hidden.has(n.kind));
    const ids = new Set(nodes.map((n) => n.id));
    let edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    if (centre && ids.has(centre)) {
      const near = neighbourhood(centre, edges);
      nodes = nodes.filter((n) => near.has(n.id));
      edges = edges.filter((e) => near.has(e.source) && near.has(e.target));
    }
    return { nodes, edges, pos: layout(nodes, edges, WIDTH, HEIGHT) };
  }, [graph, hidden, centre]);

  if (state.status === "loading") return <SkeletonRows label="Loading the graph" rows={6} />;
  if (state.status === "error") return <ErrorNotice error={state.error} onRetry={retry} />;
  if (!graph || !view) return null;

  const active = selected ? neighbourhood(selected, view.edges, 1) : null;
  const chosen = selected ? graph.nodes.find((n) => n.id === selected) : undefined;

  function toggle(kind: NodeKind) {
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }

  return (
    <div className="graph">
      <dl className="stats graph-stats">
        <div className="stat">
          <dt>Records</dt>
          <dd>
            <span className="stat-value num">{graph.nodes.length}</span>
            <span className="meta">stored</span>
          </dd>
        </div>
        <div className="stat">
          <dt>Links</dt>
          <dd>
            <span className="stat-value num">{graph.edges.length}</span>
            <span className="meta">from stored fields</span>
          </dd>
        </div>
        <div className="stat">
          <dt>People</dt>
          <dd>
            <span className="stat-value num">{graph.by_kind.person ?? 0}</span>
            <span className="meta">{graph.by_kind.report ?? 0} reports</span>
          </dd>
        </div>
      </dl>

      <div className="graph-controls">
        <label className="inline">
          Focus on
          <select
            value={centre ?? ""}
            onChange={(e) => {
              setFocus(e.target.value || null);
              setSelected(null);
            }}
          >
            <option value="">Everyone</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="layers">
          <legend className="visually-hidden">Show</legend>
          {OPTIONAL.filter((k) => graph.by_kind[k]).map((kind) => (
            <label key={kind} className="inline">
              <input type="checkbox" checked={!hidden.has(kind)} onChange={() => toggle(kind)} />
              {NODE_LABELS[kind]}
            </label>
          ))}
        </fieldset>
      </div>

      <div className="graph-frame">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={`Graph of ${view.nodes.length} records and ${view.edges.length} links`}
          onClick={() => setSelected(null)}
        >
          <g>
            {view.edges.map((e, i) => {
              const a = view.pos.get(e.source)!;
              const b = view.pos.get(e.target)!;
              const lit = active ? active.has(e.source) && active.has(e.target) : true;
              return (
                <line
                  key={i}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  className={`g-edge e-${e.kind}${lit ? "" : " dim"}`}
                >
                  <title>{EDGE_LABELS[e.kind]}</title>
                </line>
              );
            })}
          </g>
          <g>
            {view.nodes.map((n) => {
              const p = view.pos.get(n.id)!;
              const lit = active ? active.has(n.id) : true;
              const labelled = ALWAYS_LABELLED.includes(n.kind) || n.id === selected;
              const select = (ev: { stopPropagation: () => void }) => {
                ev.stopPropagation();
                setSelected(n.id === selected ? null : n.id);
              };
              return (
                <g
                  key={n.id}
                  transform={`translate(${p.x},${p.y})`}
                  className={`g-node${lit ? "" : " dim"}${n.id === selected ? " chosen" : ""}`}
                  role="button"
                  tabIndex={n.kind === "report" ? -1 : 0}
                  aria-label={`${n.label}${n.detail ? `, ${n.detail}` : ""}`}
                  onClick={select}
                  onKeyDown={(ev) => {
                    if (ev.key === "Enter" || ev.key === " ") {
                      ev.preventDefault();
                      select(ev);
                    }
                  }}
                >
                  <Shape node={n} size={n.kind === "person" ? 9 : 7} />
                  {labelled && (
                    <text y={n.kind === "person" ? -14 : -12} textAnchor="middle" className="g-label">
                      {n.label.length > 26 ? `${n.label.slice(0, 25)}...` : n.label}
                    </text>
                  )}
                  <title>{n.detail ? `${n.label}: ${n.detail}` : n.label}</title>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
      <div className="graph-legend" aria-label="Legend">
          <ul>
            <li><svg width="16" height="16" aria-hidden="true"><circle cx="8" cy="8" r="6" className="g-person" /></svg>Person</li>
            <li><svg width="16" height="16" aria-hidden="true"><rect x="3" y="3" width="10" height="10" rx="2" className="g-subject" /></svg>Road, shelter or hazard</li>
            <li><svg width="16" height="16" aria-hidden="true"><circle cx="8" cy="8" r="3" className="g-report" /></svg>Report</li>
            <li><svg width="16" height="16" aria-hidden="true"><rect x="4" y="4" width="8" height="8" transform="rotate(45 8 8)" className="g-source" /></svg>Source</li>
            <li><svg width="16" height="16" aria-hidden="true"><circle cx="8" cy="8" r="5" className="g-place" /></svg>Place</li>
            {LEGEND_EDGES.map((k) => (
              <li key={k}>
                <svg width="16" height="16" aria-hidden="true">
                  <line x1="1" y1="8" x2="15" y2="8" className={`g-edge e-${k}`} />
                </svg>
                {EDGE_LABELS[k]}
              </li>
            ))}
          </ul>
      </div>
      {chosen ? (
        <Details node={chosen} graph={graph} />
      ) : (
        <p className="meta">
          Select a record to see what it links to. Every record is stored with its real id; every
          link comes from a stored field, never a guess.
        </p>
      )}
    </div>
  );
}
