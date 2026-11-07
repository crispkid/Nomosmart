import type { GraphExplorerEdge, GraphExplorerNode } from "@/components/GraphExplorer";

export const GRAPH_LAYOUT_VERSION = "force-400-v1";
export const GRAPH_WIDTH = 1080;
export const GRAPH_HEIGHT = 640;
export type GraphPosition = { x: number; y: number };
export type GraphPositions = Record<string, GraphPosition>;
export type LayoutNode = Pick<GraphExplorerNode, "id" | "kind" | "x" | "y" | "semanticLayer"> & { width: number; height: number };
export type LayoutEdge = Pick<GraphExplorerEdge, "id" | "source" | "target">;
export type LayoutSnapshot = { version: string; nodes: LayoutNode[]; edges: LayoutEdge[] };
export type LayoutRequest = { id: number; snapshot: LayoutSnapshot };
export type LayoutReply = { id: number; positions: GraphPositions } | { id: number; error: "graph_layout_failed" };

export function graphNodeDimensions(node: Pick<GraphExplorerNode, "kind">) {
  if (node.kind === "project") return { w: 160, h: 160, type: "circle" as const };
  if (node.kind === "document") return { w: 160, h: 64, type: "rect" as const };
  if (node.kind === "chunk") return { w: 140, h: 48, type: "rect" as const };
  if (node.kind === "tag") return { w: 100, h: 32, type: "rect" as const };
  return { w: 120, h: 48, type: "rect" as const };
}

/** Copy only geometry. Document text and metadata never cross the Worker boundary. */
export function graphLayoutSnapshot(nodes: GraphExplorerNode[], edges: GraphExplorerEdge[]): LayoutSnapshot {
  return { version: GRAPH_LAYOUT_VERSION, nodes: nodes.map(node => {
    const size = graphNodeDimensions(node);
    return { id: node.id, kind: node.kind, x: node.x, y: node.y, semanticLayer: node.semanticLayer, width: size.w, height: size.h };
  }), edges: edges.map(({ id, source, target }) => ({ id, source, target })) };
}

export async function graphSourceDigest(source: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(source));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), value => value.toString(16).padStart(2, "0")).join("");
}

export function validGraphPositions(value: unknown, nodes: LayoutNode[]): value is GraphPositions {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const positions = value as GraphPositions;
  const ids = new Set(nodes.map(node => node.id));
  if (Object.keys(positions).length !== ids.size || ids.size !== nodes.length) return false;
  return nodes.every(node => Object.hasOwn(positions, node.id) && Number.isFinite(positions[node.id]?.x) && Number.isFinite(positions[node.id]?.y));
}
