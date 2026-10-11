import { useMemo, useRef, useState, type PointerEvent } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/context";
import {
  EDGE_LABELS,
  EDGE_PHRASES,
  getIncidentGraph,
  NODE_LABELS,
  NODE_NAME,
  type EdgeKind,
  type GraphEdge,
  type GraphNode,
  type IncidentGraph,
  type NodeKind,
} from "../api/graph";
import { layout, neighbourhood, type Point } from "../graphLayout";
import { useLoad } from "../useLoad";
import { ErrorNotice } from "./ErrorNotice";
import { SkeletonRows } from "./ui";

const WIDTH = 1000;
const HEIGHT = 620;
const OPTIONAL: NodeKind[] = ["report", "source", "place", "subject", "investigation"];
const ALWAYS_LABELLED: NodeKind[] = ["person", "subject", "source", "place"];
const LEGEND_EDGES: EdgeKind[] = ["about", "from", "mentions", "relays", "possibly_same", "same_person"];
const KIND_ORDER: NodeKind[] = ["person", "subject", "report", "source", "place", "investigation"];
// Links that are a proposal, not a stored fact, are drawn dashed (as in Trace).
const CANDIDATE: EdgeKind[] = ["possibly_same"];

function size(kind: NodeKind): number {
  return kind === "person" ? 9 : 7;
}

function Shape({ node }: { node: GraphNode }) {
  const s = size(node.kind);
  switch (node.kind) {
    case "person":
      return <circle r={s} className="g-person" />;
    case "subject":
      return <rect x={-s} y={-s} width={s * 2} height={s * 2} rx={2} className="g-subject" />;
    case "report":
      return <circle r={s * 0.45} className="g-report" />;
    case "source":
      return <rect x={-s} y={-s} width={s * 2} height={s * 2} transform="rotate(45)" className="g-source" />;
    case "place":
      return <circle r={s * 0.8} className="g-place" />;
    default:
      return <rect x={-s} y={-s} width={s * 2} height={s * 2} rx={3} className="g-investigation" />;
  }
}

/** A slightly bent link that stops short of its target, so the arrowhead shows. */
function linkPath(a: Point, b: Point, trim: number): string {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const qx = (a.x + b.x) / 2 - dy * 0.12;
  const qy = (a.y + b.y) / 2 + dx * 0.12;
  const tx = b.x - qx;
  const ty = b.y - qy;
  const len = Math.max(Math.hypot(tx, ty), 1);
  const end = { x: b.x - (tx / len) * trim, y: b.y - (ty / len) * trim };
  const f = (v: number) => Math.round(v * 10) / 10;
  return `M ${f(a.x)} ${f(a.y)} Q ${f(qx)} ${f(qy)} ${f(end.x)} ${f(end.y)}`;
}

function openLink(node: GraphNode, graph: IncidentGraph): string | null {
  if (node.kind === "person") return `/people/${encodeURIComponent(node.id)}`;
  if (node.kind === "investigation") return `/investigations/${encodeURIComponent(node.id)}`;
  const subjectOf = graph.edges.find((e) => e.source === node.id && e.kind === "about")?.target;
  if (node.kind === "report" && subjectOf && graph.nodes.find((n) => n.id === subjectOf)?.kind === "person") {
    return `/people/${encodeURIComponent(subjectOf)}#entry-${node.id}`;
  }
  return null;
}

function LinkRow({
  edge,
  other,
  outgoing,
  self,
  onSelect,
}: {
  edge: GraphEdge;
  other: GraphNode | undefined;
  outgoing: boolean;
  self: GraphNode;
  onSelect: (id: string) => void;
}) {
  const otherId = outgoing ? edge.target : edge.source;
  const phrase = EDGE_PHRASES[edge.kind];
  return (
    <li className={CANDIDATE.includes(edge.kind) ? "link-row candidate" : "link-row"}>
      <button type="button" onClick={() => other && onSelect(otherId)} disabled={!other}>
        <span className="link-kind">
          {outgoing ? "→" : "←"} {edge.kind}
        </span>
        <span>
          {outgoing ? (
            <>
              {self.label} {phrase} <strong>{other?.label ?? "a record outside this view"}</strong>
            </>
          ) : (
            <>
              <strong>{other?.label ?? "a record outside this view"}</strong> {phrase} this record
            </>
          )}
        </span>
        <span className="meta mono">
          {other ? NODE_NAME[other.kind] : "Unknown"} {otherId}
        </span>
      </button>
    </li>
  );
}

/** One record, its id and every link into and out of it, as in Trace's inspector. */
function Inspector({
  node,
  graph,
  onSelect,
}: {
  node: GraphNode | undefined;
  graph: IncidentGraph;
  onSelect: (id: string) => void;
}) {
  if (!node) {
    return (
      <div className="graph-details empty-small">
        <h3>Select a record</h3>
        <p className="meta">
          Pick any record in the diagram or the list to see what it is and how it connects.
        </p>
      </div>
    );
  }
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const outgoing = graph.edges.filter((e) => e.source === node.id);
  const incoming = graph.edges.filter((e) => e.target === node.id);
  const to = openLink(node, graph);
  return (
    <article className="graph-details" aria-live="polite" aria-label={`Record: ${node.label}`}>
      <header>
        <p className="eyebrow">{NODE_NAME[node.kind]}</p>
        <h3>{node.label}</h3>
        {node.detail && <p className="meta">{node.detail}</p>}
        <p className="meta mono">{node.id}</p>
        {to && <Link to={to}>Open</Link>}
      </header>
      <section>
        <h4>Outgoing links ({outgoing.length})</h4>
        {outgoing.length === 0 ? (
          <p className="meta">No outgoing links.</p>
        ) : (
          <ul className="link-list">
            {outgoing.map((e, i) => (
              <LinkRow key={i} edge={e} other={byId.get(e.target)} outgoing self={node} onSelect={onSelect} />
            ))}
          </ul>
        )}
      </section>
      <section>
        <h4>Incoming links ({incoming.length})</h4>
        {incoming.length === 0 ? (
          <p className="meta">No incoming links.</p>
        ) : (
          <ul className="link-list">
            {incoming.map((e, i) => (
              <LinkRow key={i} edge={e} other={byId.get(e.source)} outgoing={false} self={node} onSelect={onSelect} />
            ))}
          </ul>
        )}
      </section>
    </article>
  );
}

/** Every record in a searchable list, grouped by kind: the keyboard way into the graph. */
function RecordFinder({
  nodes,
  selected,
  onSelect,
}: {
  nodes: GraphNode[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const visible = nodes.filter(
    (n) =>
      !q ||
      n.label.toLowerCase().includes(q) ||
      NODE_NAME[n.kind].toLowerCase().includes(q) ||
      n.id.toLowerCase().includes(q),
  );
  return (
    <nav className="record-finder" aria-label="Graph records">
      <label className="search-field">
        <span>Find a record</span>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Name, kind or id"
        />
      </label>
      <div className="record-groups">
        {visible.length === 0 && <p className="meta">No records match.</p>}
        {KIND_ORDER.map((kind) => {
          const group = visible.filter((n) => n.kind === kind);
          if (group.length === 0) return null;
          return (
            <section key={kind}>
              <h3>
                {NODE_LABELS[kind]} ({group.length})
              </h3>
              <ul>
                {group.map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      className={n.id === selected ? "record-item active" : "record-item"}
                      aria-current={n.id === selected ? "true" : undefined}
                      onClick={() => onSelect(n.id)}
                    >
                      <span>{n.label}</span>
                      <span className="meta mono">{n.id}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </nav>
  );
}

/** Every stored record of the incident and the typed links between them. */
export function GraphView({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const [state, retry] = useLoad(`graph|${incidentId}`, () => getIncidentGraph(api, incidentId));
  const [hidden, setHidden] = useState<Set<NodeKind>>(new Set());
  const [focus, setFocus] = useState<string | null | undefined>(undefined);
  const [selected, setSelected] = useState<string | null>(null);
  // Records the person dragged, by id; cleared by "Re-run layout" or a new view.
  const [moved, setMoved] = useState<Record<string, Point>>({});
  const drag = useRef<{ id: string; travelled: boolean } | null>(null);

  const graph = state.status === "ready" ? state.data : null;
  const people = useMemo(
    () => (graph ? graph.nodes.filter((n) => n.kind === "person").sort((a, b) => a.label.localeCompare(b.label)) : []),
    [graph],
  );
  // The demo opens on Sita, the person its story follows; elsewhere, everything.
  const centre =
    focus === undefined ? (people.find((p) => p.label === "Sita Tamang")?.id ?? null) : focus;

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
  const at = (id: string): Point => moved[id] ?? view.pos.get(id)!;
  const kindOf = new Map(view.nodes.map((n) => [n.id, n.kind]));
  const candidates = graph.edges.filter((e) => CANDIDATE.includes(e.kind)).length;

  function toggle(kind: NodeKind) {
    setMoved({});
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }

  function svgPoint(svg: SVGSVGElement, e: PointerEvent): Point {
    const box = svg.getBoundingClientRect();
    return {
      x: ((e.clientX - box.left) / Math.max(box.width, 1)) * WIDTH,
      y: ((e.clientY - box.top) / Math.max(box.height, 1)) * HEIGHT,
    };
  }

  function onPointerMove(e: PointerEvent<SVGSVGElement>) {
    const current = drag.current;
    if (!current) return;
    current.travelled = true;
    const p = svgPoint(e.currentTarget, e);
    setMoved((m) => ({ ...m, [current.id]: p }));
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
            <span className="stat-value num">{graph.edges.length - candidates}</span>
            <span className="meta">from stored fields</span>
          </dd>
        </div>
        <div className="stat">
          <dt>Proposed links</dt>
          <dd>
            <span className="stat-value num">{candidates}</span>
            <span className="meta">a reviewer decides</span>
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
              setMoved({});
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

      <figure className="graph-figure">
        <div className="graph-frame">
          <div className="graph-toolbar">
            <span className="pill accent">{centre ? "Focused" : "This incident"}</span>
            <span className="meta">
              {view.nodes.length} records, {view.edges.length} links
            </span>
            <button
              type="button"
              className="small"
              onClick={() => setMoved({})}
              disabled={Object.keys(moved).length === 0}
            >
              Re-run layout
            </button>
          </div>
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            role="img"
            aria-label={`Graph of ${view.nodes.length} records and ${view.edges.length} links`}
            onClick={() => setSelected(null)}
            onPointerMove={onPointerMove}
            onPointerUp={() => {
              drag.current = null;
            }}
            onPointerCancel={() => {
              drag.current = null;
            }}
          >
            <defs>
              <marker
                id="graph-arrow"
                viewBox="0 0 10 10"
                refX="10"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M0,0 L10,5 L0,10 z" className="g-arrow" />
              </marker>
            </defs>
            <g>
              {view.edges.map((e, i) => {
                const lit = active ? active.has(e.source) && active.has(e.target) : true;
                const touching = e.source === selected || e.target === selected;
                return (
                  <path
                    key={i}
                    d={linkPath(at(e.source), at(e.target), size(kindOf.get(e.target)!) + 3)}
                    fill="none"
                    markerEnd="url(#graph-arrow)"
                    className={`g-edge e-${e.kind}${lit ? "" : " dim"}${touching ? " touching" : ""}`}
                  >
                    <title>{EDGE_LABELS[e.kind]}</title>
                  </path>
                );
              })}
            </g>
            <g>
              {view.nodes.map((n) => {
                const p = at(n.id);
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
                    onPointerDown={(ev) => {
                      drag.current = { id: n.id, travelled: false };
                      ev.currentTarget.ownerSVGElement?.setPointerCapture?.(ev.pointerId);
                    }}
                    onClick={(ev) => {
                      // A drag that moved the record is not a click.
                      if (drag.current?.travelled) {
                        ev.stopPropagation();
                        drag.current = null;
                        return;
                      }
                      drag.current = null;
                      select(ev);
                    }}
                    onKeyDown={(ev) => {
                      if (ev.key === "Enter" || ev.key === " ") {
                        ev.preventDefault();
                        select(ev);
                      }
                    }}
                  >
                    <Shape node={n} />
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
        <figcaption className="meta">
          Drawn from the stored records. Drag a record to move it; select one to see its links.
          Arrows follow the stored direction; dashed links are proposals a reviewer has not
          decided.
        </figcaption>
      </figure>
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
      <div className="graph-browse">
        <RecordFinder nodes={graph.nodes} selected={selected} onSelect={setSelected} />
        <Inspector node={chosen} graph={graph} onSelect={setSelected} />
      </div>
    </div>
  );
}
