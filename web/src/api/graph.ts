/** The incident as stored records and the typed links between them. */

import type { ApiClient } from "./client";

export type NodeKind = "person" | "subject" | "report" | "source" | "place" | "investigation";
export type EdgeKind =
  | "about"
  | "from"
  | "at"
  | "mentions"
  | "traced"
  | "relays"
  | "possibly_same"
  | "same_person"
  | "not_same";

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  detail: string | null;
  subject_type: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: EdgeKind;
}

export interface IncidentGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  by_kind: Partial<Record<NodeKind, number>>;
}

export const NODE_LABELS: Record<NodeKind, string> = {
  person: "People",
  subject: "Roads, shelters, hazards",
  report: "Reports",
  source: "Sources",
  place: "Places",
  investigation: "Investigations",
};

export const NODE_NAME: Record<NodeKind, string> = {
  person: "Person",
  subject: "Road, shelter or hazard",
  report: "Report",
  source: "Source",
  place: "Place",
  investigation: "Investigation",
};

export const EDGE_LABELS: Record<EdgeKind, string> = {
  about: "report is about",
  from: "report is from",
  at: "report names the place",
  mentions: "report names another source",
  traced: "investigation of the report",
  relays: "finding: relays this source",
  possibly_same: "possibly the same person",
  same_person: "confirmed the same person",
  not_same: "checked: not the same person",
};

/** A link read in its stored direction: "<record> is about <other record>". */
export const EDGE_PHRASES: Record<EdgeKind, string> = {
  about: "is about",
  from: "is from",
  at: "names the place",
  mentions: "names the source",
  traced: "investigates",
  relays: "found it relays",
  possibly_same: "may be the same person as",
  same_person: "is the same person as",
  not_same: "is not the same person as",
};

export function getIncidentGraph(api: ApiClient, incidentId: string): Promise<IncidentGraph> {
  return api.get<IncidentGraph>(`/v1/incidents/${encodeURIComponent(incidentId)}/graph`);
}
