/**
 * A small force-directed layout (Fruchterman and Reingold) for the incident graph.
 * Deterministic: start positions come from each node's id, so the same graph always
 * lands in the same shape and nothing jumps between visits.
 */

export interface LayoutNode {
  id: string;
}

export interface LayoutEdge {
  source: string;
  target: string;
}

export interface Point {
  x: number;
  y: number;
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Positions inside [0, width] x [0, height], keyed by node id. */
export function layout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  width: number,
  height: number,
  iterations = 300,
): Map<string, Point> {
  const n = nodes.length;
  const pos = new Map<string, Point>();
  if (n === 0) return pos;
  const area = width * height;
  const k = Math.sqrt(area / n) * 0.75;
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const xs = new Float64Array(n);
  const ys = new Float64Array(n);
  nodes.forEach((node, i) => {
    const h = hash(node.id);
    xs[i] = ((h & 0xffff) / 0xffff) * width;
    ys[i] = ((h >>> 16) / 0xffff) * height;
  });
  const links = edges
    .map((e) => [index.get(e.source), index.get(e.target)] as const)
    .filter((pair): pair is readonly [number, number] => pair[0] !== undefined && pair[1] !== undefined);

  let temperature = width / 8;
  const cooling = temperature / (iterations + 1);
  const dx = new Float64Array(n);
  const dy = new Float64Array(n);
  for (let step = 0; step < iterations; step++) {
    dx.fill(0);
    dy.fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let ddx = xs[i]! - xs[j]!;
        let ddy = ys[i]! - ys[j]!;
        let dist = Math.hypot(ddx, ddy);
        if (dist < 0.01) {
          ddx = 0.01 * (i - j);
          ddy = 0.01;
          dist = Math.hypot(ddx, ddy);
        }
        const force = (k * k) / dist;
        const fx = (ddx / dist) * force;
        const fy = (ddy / dist) * force;
        dx[i]! += fx;
        dy[i]! += fy;
        dx[j]! -= fx;
        dy[j]! -= fy;
      }
    }
    for (const [a, b] of links) {
      const ddx = xs[a]! - xs[b]!;
      const ddy = ys[a]! - ys[b]!;
      const dist = Math.max(Math.hypot(ddx, ddy), 0.01);
      const force = (dist * dist) / k;
      const fx = (ddx / dist) * force;
      const fy = (ddy / dist) * force;
      dx[a]! -= fx;
      dy[a]! -= fy;
      dx[b]! += fx;
      dy[b]! += fy;
    }
    for (let i = 0; i < n; i++) {
      // A gentle pull to the middle keeps loose pieces on the page.
      dx[i]! += (width / 2 - xs[i]!) * 0.02;
      dy[i]! += (height / 2 - ys[i]!) * 0.02;
      const d = Math.max(Math.hypot(dx[i]!, dy[i]!), 0.01);
      xs[i] = xs[i]! + (dx[i]! / d) * Math.min(d, temperature);
      ys[i] = ys[i]! + (dy[i]! / d) * Math.min(d, temperature);
    }
    temperature -= cooling;
  }

  // Fit the result into the box with a margin.
  const margin = 40;
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const sx = (width - 2 * margin) / Math.max(maxX - minX, 1);
  const sy = (height - 2 * margin) / Math.max(maxY - minY, 1);
  nodes.forEach((node, i) => {
    pos.set(node.id, {
      x: n === 1 ? width / 2 : margin + (xs[i]! - minX) * sx,
      y: n === 1 ? height / 2 : margin + (ys[i]! - minY) * sy,
    });
  });
  return pos;
}

/** The nodes within `hops` links of `centre`, for focusing on one person. */
export function neighbourhood(centre: string, edges: LayoutEdge[], hops = 2): Set<string> {
  const keep = new Set([centre]);
  let frontier = new Set([centre]);
  for (let h = 0; h < hops; h++) {
    const next = new Set<string>();
    for (const e of edges) {
      if (frontier.has(e.source) && !keep.has(e.target)) next.add(e.target);
      if (frontier.has(e.target) && !keep.has(e.source)) next.add(e.source);
    }
    next.forEach((id) => keep.add(id));
    frontier = next;
  }
  return keep;
}
