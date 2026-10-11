import { describe, expect, it } from "vitest";

import { layout, neighbourhood } from "./graphLayout";

const NODES = ["a", "b", "c", "d", "e"].map((id) => ({ id }));
const EDGES = [
  { source: "a", target: "b" },
  { source: "b", target: "c" },
  { source: "c", target: "d" },
];

describe("graph layout", () => {
  it("is deterministic and stays inside the box", () => {
    const first = layout(NODES, EDGES, 400, 300);
    const second = layout(NODES, EDGES, 400, 300);
    expect([...first.entries()]).toEqual([...second.entries()]);
    for (const p of first.values()) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(400);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(300);
    }
  });

  it("keeps linked nodes closer than unlinked ones on average", () => {
    const pos = layout(NODES, EDGES, 400, 300);
    const dist = (a: string, b: string) => {
      const p = pos.get(a)!;
      const q = pos.get(b)!;
      return Math.hypot(p.x - q.x, p.y - q.y);
    };
    expect(dist("a", "b")).toBeLessThan(dist("a", "e") + dist("b", "e"));
  });

  it("handles empty and single-node graphs", () => {
    expect(layout([], [], 100, 100).size).toBe(0);
    expect(layout([{ id: "x" }], [], 100, 80).get("x")).toEqual({ x: 50, y: 40 });
  });

  it("finds the nodes within a number of links", () => {
    expect([...neighbourhood("a", EDGES, 1)].sort()).toEqual(["a", "b"]);
    expect([...neighbourhood("a", EDGES, 2)].sort()).toEqual(["a", "b", "c"]);
    expect([...neighbourhood("e", EDGES)]).toEqual(["e"]);
  });
});
