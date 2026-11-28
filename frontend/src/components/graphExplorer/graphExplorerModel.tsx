"use client";

// Graph explorer node/edge types, zoom bands and geometry helpers (split from GraphExplorer, OPT424-038).
import { graphVisualScale, MIN_GRAPH_ZOOM, MAX_GRAPH_ZOOM } from "@/lib/graphZoom";
import { useMemo } from "react";
import { GRAPH_HEIGHT, GRAPH_WIDTH, graphNodeDimensions } from "@/lib/graphLayoutProtocol";
import { BarChart3, FileText, FolderKanban, ImageIcon, Layers, Table2, Tag, TextQuote } from "lucide-react";
import { type TranslationKey } from "@/lib/i18nClient";

export type GraphExplorerNodeKind = "project" | "document" | "chunk" | "tag" | "group";
export type GraphExplorerContentType = "text" | "image" | "table" | "chart";
type GraphExplorerSemanticLayer = 1 | 2 | 3 | 4;

type GraphExplorerMeta = {
  label: string;
  value: string;
};

export type GraphExplorerNode = {
  chunkContent?: string;
  chunkDisplayMarkdown?: string | null;
  chunkIndex?: number;
  chunkMarkdownContent?: string | null;
  contentType?: GraphExplorerContentType;
  focusParentId?: string;
  groupCount?: number;
  hideWhenParentSelectedId?: string;
  hintUntilZoom?: number;
  id: string;
  kind: GraphExplorerNodeKind;
  maxZoom?: number;
  meta?: GraphExplorerMeta[];
  minZoom?: number;
  revealAtZoom?: number;
  semanticLayer?: GraphExplorerSemanticLayer;
  subtitle?: string;
  technicalId?: string;
  title: string;
  x: number;
  y: number;
};

export type GraphExplorerEdge = {
  id: string;
  label: string;
  meta?: GraphExplorerMeta[];
  relation: "contains" | "references" | "semantic" | "source" | "supersedes" | "tagged_as";
  showLabel?: boolean;
  source: string;
  target: string;
};


export const MIN_ZOOM = MIN_GRAPH_ZOOM;
export const MAX_ZOOM = MAX_GRAPH_ZOOM;


type GraphZoomBand = "structure" | "chunk" | "tag" | "inspection";
export type VisibleGraphExplorerNode = GraphExplorerNode & { isHint?: boolean };
export type GraphPanExtent = { minX: number; maxX: number; minY: number; maxY: number; nodeWidth: number; nodeHeight: number };

export const contentTypeLabelKeys: Record<GraphExplorerContentType, TranslationKey> = {
  chart: "graphContentChart",
  image: "graphContentImage",
  table: "graphContentTable",
  text: "graphContentText"
};

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function semanticZoomBand(zoom: number): GraphZoomBand {
  if (zoom >= 2.5) return "inspection";
  if (zoom >= 2) return "tag";
  if (zoom >= 1.5) return "chunk";
  return "structure";
}

export function visualScaleForZoom(zoom: number) {
  return graphVisualScale(zoom);
}

export function constrainGraphPan(position: { x: number; y: number }, extent: GraphPanExtent | null, width: number, height: number, scale: number) {
  if (!extent) return { x: 0, y: 0 };
  // Leave room for a complete outer node while allowing every node to reach the
  // viewport centre. Limits follow the layout, including manual positions.
  const travelX = Math.max(0, (width - extent.nodeWidth * scale) / 2 - 16);
  const travelY = Math.max(0, (height - extent.nodeHeight * scale) / 2 - 16);
  return {
    x: clamp(position.x, Math.min(0, (GRAPH_WIDTH / 2 - extent.maxX) * scale - travelX), Math.max(0, (GRAPH_WIDTH / 2 - extent.minX) * scale + travelX)),
    y: clamp(position.y, Math.min(0, (GRAPH_HEIGHT / 2 - extent.maxY) * scale - travelY), Math.max(0, (GRAPH_HEIGHT / 2 - extent.minY) * scale + travelY))
  };
}

export function nodeVisibilityAtZoom(node: GraphExplorerNode, zoom: number, selectedNodeId: string | null) {
  if (selectedNodeId && node.hideWhenParentSelectedId === selectedNodeId) return { hint: false, visible: false };
  const selectedFocus = Boolean(selectedNodeId && node.focusParentId === selectedNodeId);
  if (selectedFocus || node.id === selectedNodeId) return { hint: false, visible: true };
  if (node.revealAtZoom && zoom < node.revealAtZoom) {
    const showHint = Boolean(node.hintUntilZoom && zoom < node.hintUntilZoom);
    return { hint: showHint, visible: showHint };
  }
  if (node.maxZoom && zoom > node.maxZoom) return { hint: false, visible: false };
  if (node.minZoom && zoom < node.minZoom) return { hint: false, visible: false };
  if ((node.semanticLayer === 3 && zoom < 1.5) || (node.semanticLayer === 4 && zoom < 2)) return { hint: true, visible: true };
  return { hint: false, visible: true };
}

export const nodeDimensions = graphNodeDimensions;

function edgeEndpoint(from: GraphExplorerNode, to: GraphExplorerNode, paddingOverride?: number) {
  const { w, h, type } = nodeDimensions(from);
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const absDx = Math.abs(dx);
  const absDy = Math.abs(dy);
  
  if (type === "circle") {
    const r = (w / 2) + (paddingOverride ?? 0);
    const len = Math.hypot(dx, dy) || 1;
    return { x: from.x + (dx / len) * r, y: from.y + (dy / len) * r };
  }
  
  const targetW = (w / 2) + (paddingOverride ?? 0);
  const targetH = (h / 2) + (paddingOverride ?? 0);
  
  const scaleX = absDx > 0 ? targetW / absDx : Infinity;
  const scaleY = absDy > 0 ? targetH / absDy : Infinity;
  const scale = Math.min(scaleX, scaleY);
  
  // If the nodes are overlapping such that the scale is > 1, cap it to avoid line extending beyond target
  const clampedScale = Math.min(scale, 0.95);
  
  return {
    x: from.x + dx * clampedScale,
    y: from.y + dy * clampedScale
  };
}

export function edgePath(source: GraphExplorerNode, target: GraphExplorerNode) {
  const start = edgeEndpoint(source, target, 0);
  const end = edgeEndpoint(target, source, 0);
  return `M ${start.x} ${start.y} L ${end.x} ${end.y}`;
}

export function edgeLabelPosition(source: GraphExplorerNode, target: GraphExplorerNode) {
  const x = (source.x + target.x) / 2;
  const y = (source.y + target.y) / 2;
  return {
    x,
    y: y - 8
  };
}

export function nodeTypeKey(kind: GraphExplorerNodeKind): TranslationKey {
  if (kind === "project") return "graphLegendProject";
  if (kind === "document") return "graphLegendDocument";
  if (kind === "chunk") return "graphLegendChunk";
  if (kind === "tag") return "graphLegendTag";
  return "graphExplorerGroup";
}

export function GraphNodeIcon({ contentType, kind }: { contentType?: GraphExplorerContentType; kind: GraphExplorerNodeKind }) {
  if (kind === "project") return <FolderKanban size={18} />;
  if (kind === "document") return <FileText size={18} />;
  if (kind === "tag") return <Tag size={16} />;
  if (kind === "group") return <Layers size={16} />;
  if (contentType === "image") return <ImageIcon size={16} />;
  if (contentType === "table") return <Table2 size={16} />;
  if (contentType === "chart") return <BarChart3 size={16} />;
  // CHG-495 DESIGN.md §8: text chunks use TextQuote; images, tables and charts keep their own icon.
  return <TextQuote size={16} />;
}

export type GraphRelation = GraphExplorerEdge["relation"];

/** CHG-495 M23: labels of the relation filter (the edge label itself can be a source name such as "Upload"). */
export const relationFilterLabelKeys: Record<GraphRelation, TranslationKey> = {
  contains: "graphLegendContains",
  references: "graphRelationReferences",
  semantic: "graphRelationSemantic",
  source: "graphRelationSourceFilter",
  supersedes: "graphRelationSupersedes",
  tagged_as: "graphRelationTaggedAs"
};

export const graphNodeKinds: GraphExplorerNodeKind[] = ["project", "document", "chunk", "tag", "group"];
export const graphContentTypes: GraphExplorerContentType[] = ["text", "image", "table", "chart"];
export const graphRelations: GraphRelation[] = ["source", "contains", "tagged_as", "references", "supersedes", "semantic"];
/** Backend node types (`node_type_counts`) for each explorer node kind. */
export const graphKindTotalsKey: Partial<Record<GraphExplorerNodeKind, string>> = { project: "Project", document: "Document", chunk: "Chunk", tag: "Tag" };

/** CHG-495 M23: hidden node kinds, chunk content types and relations, plus the neighbourhood depth around the selected node. */
export type GraphFilters = {
  depth: "all" | 1 | 2;
  hiddenContentTypes: GraphExplorerContentType[];
  hiddenKinds: GraphExplorerNodeKind[];
  hiddenRelations: GraphRelation[];
};

export const defaultGraphFilters: GraphFilters = { depth: "all", hiddenContentTypes: [], hiddenKinds: [], hiddenRelations: [] };

export function graphFiltersActive(filters: GraphFilters) {
  return filters.depth !== "all" || filters.hiddenContentTypes.length > 0 || filters.hiddenKinds.length > 0 || filters.hiddenRelations.length > 0;
}

/**
 * Filters only what is drawn; the layout keeps every node so positions and the layout cache do not change.
 * A depth limit applies while a node is selected: nodes further than `depth` hops (over shown edges) are hidden.
 */
export function applyGraphFilters<TNode extends GraphExplorerNode>(nodes: TNode[], edges: GraphExplorerEdge[], filters: GraphFilters, selectedNodeId: string | null) {
  const kept = nodes.filter((node) => !filters.hiddenKinds.includes(node.kind)
    && !(node.kind === "chunk" && filters.hiddenContentTypes.includes(node.contentType ?? "text")));
  const keptIds = new Set(kept.map((node) => node.id));
  const keptEdges = edges.filter((edge) => !filters.hiddenRelations.includes(edge.relation) && keptIds.has(edge.source) && keptIds.has(edge.target));
  if (filters.depth === "all" || !selectedNodeId || !keptIds.has(selectedNodeId)) return { edges: keptEdges, nodes: kept };
  const reached = new Set([selectedNodeId]);
  let frontier = [selectedNodeId];
  for (let level = 0; level < filters.depth && frontier.length; level += 1) {
    const next: string[] = [];
    for (const edge of keptEdges) {
      for (const [from, to] of [[edge.source, edge.target], [edge.target, edge.source]]) {
        if (frontier.includes(from) && !reached.has(to)) { reached.add(to); next.push(to); }
      }
    }
    frontier = next;
  }
  return { edges: keptEdges.filter((edge) => reached.has(edge.source) && reached.has(edge.target)), nodes: kept.filter((node) => reached.has(node.id)) };
}

export function useRelationMap<TNode extends GraphExplorerNode>(nodes: TNode[], edges: GraphExplorerEdge[], selected: { id: string; type: "edge" | "node" } | null) {
  return useMemo(() => {
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const edgeById = new Map(edges.map((edge) => [edge.id, edge]));
    const relatedNodeIds = new Set<string>();
    const relatedEdgeIds = new Set<string>();

    if (selected?.type === "node") {
      relatedNodeIds.add(selected.id);
      for (const edge of edges) {
        if (edge.source !== selected.id && edge.target !== selected.id) continue;
        relatedEdgeIds.add(edge.id);
        relatedNodeIds.add(edge.source);
        relatedNodeIds.add(edge.target);
      }
    }

    if (selected?.type === "edge") {
      const edge = edgeById.get(selected.id);
      if (edge) {
        relatedEdgeIds.add(edge.id);
        relatedNodeIds.add(edge.source);
        relatedNodeIds.add(edge.target);
      }
    }

    return { edgeById, nodeById, relatedEdgeIds, relatedNodeIds };
  }, [edges, nodes, selected]);
}
