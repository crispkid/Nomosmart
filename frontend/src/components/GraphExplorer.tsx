"use client";

import { type PointerEvent, type WheelEvent, useEffect, useMemo, useRef, useState } from "react";
import { graphNodeDimensions } from "@/lib/graphLayoutProtocol";
import { useGraphLayout } from "@/lib/useGraphLayout";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { BarChart3, FileText, FolderKanban, ImageIcon, Info, Link2, Network, RotateCcw, Scissors, Table2, Tag, ZoomIn, ZoomOut } from "lucide-react";
import { ChunkMarkdownView } from "@/components/ChunkMarkdownView";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";

export type GraphExplorerNodeKind = "project" | "document" | "chunk" | "tag" | "group";
export type GraphExplorerContentType = "text" | "image" | "table" | "chart";
export type GraphExplorerSemanticLayer = 1 | 2 | 3 | 4;

export type GraphExplorerMeta = {
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
  relation: "contains" | "references" | "semantic" | "source" | "tagged_as";
  showLabel?: boolean;
  source: string;
  target: string;
};

type GraphExplorerProps = {
  edges: GraphExplorerEdge[];
  emptyMessage?: string;
  layout?: "umbrella";
  layoutScope?: string;
  layoutBinding?: string | null;
  nodes: GraphExplorerNode[];
  onNodeSelect?: (nodeId: string) => void;
  scopeLabel: string;
  statusLabel?: string;
  title: string;
};

const MIN_ZOOM = 0.01;
const MAX_ZOOM = 3;


type GraphZoomBand = "structure" | "chunk" | "tag" | "inspection";
type VisibleGraphExplorerNode = GraphExplorerNode & { isHint?: boolean };

const contentTypeLabelKeys: Record<GraphExplorerContentType, TranslationKey> = {
  chart: "graphContentChart",
  image: "graphContentImage",
  table: "graphContentTable",
  text: "graphContentText"
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function semanticZoomBand(zoom: number): GraphZoomBand {
  if (zoom >= 2.5) return "inspection";
  if (zoom >= 2) return "tag";
  if (zoom >= 1.5) return "chunk";
  return "structure";
}

function visualScaleForZoom(zoom: number) {
  return zoom;
}

function nodeVisibilityAtZoom(node: GraphExplorerNode, zoom: number, selectedNodeId: string | null) {
  if (selectedNodeId && node.hideWhenParentSelectedId === selectedNodeId) return { hint: false, visible: false };
  const selectedFocus = Boolean(selectedNodeId && node.focusParentId === selectedNodeId);
  if (selectedFocus || node.id === selectedNodeId) return { hint: false, visible: true };
  if (node.revealAtZoom && zoom < node.revealAtZoom) {
    const showHint = Boolean(node.hintUntilZoom && zoom < node.hintUntilZoom);
    return { hint: showHint, visible: showHint };
  }
  if (node.maxZoom && zoom > node.maxZoom) return { hint: false, visible: false };
  if (node.minZoom && zoom < node.minZoom) return { hint: false, visible: false };
  return { hint: false, visible: true };
}

const nodeDimensions = graphNodeDimensions;

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

function edgePath(source: GraphExplorerNode, target: GraphExplorerNode) {
  const start = edgeEndpoint(source, target, 0);
  const end = edgeEndpoint(target, source, 0);
  return `M ${start.x} ${start.y} L ${end.x} ${end.y}`;
}

function edgeLabelPosition(source: GraphExplorerNode, target: GraphExplorerNode) {
  const x = (source.x + target.x) / 2;
  const y = (source.y + target.y) / 2;
  return {
    x,
    y: y - 8
  };
}

function nodeTypeKey(kind: GraphExplorerNodeKind): TranslationKey {
  if (kind === "project") return "graphLegendProject";
  if (kind === "document") return "graphLegendDocument";
  if (kind === "chunk") return "graphLegendChunk";
  if (kind === "tag") return "graphLegendTag";
  return "graphExplorerGroup";
}

function GraphNodeIcon({ contentType, kind }: { contentType?: GraphExplorerContentType; kind: GraphExplorerNodeKind }) {
  if (kind === "project") return <FolderKanban size={18} />;
  if (kind === "document") return <FileText size={18} />;
  if (kind === "tag") return <Tag size={16} />;
  if (kind === "group") return <Network size={16} />;
  if (contentType === "image") return <ImageIcon size={16} />;
  if (contentType === "table") return <Table2 size={16} />;
  if (contentType === "chart") return <BarChart3 size={16} />;
  return <Scissors size={16} />;
}

function useRelationMap<TNode extends GraphExplorerNode>(nodes: TNode[], edges: GraphExplorerEdge[], selected: { id: string; type: "edge" | "node" } | null) {
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

export function GraphExplorer({ edges, emptyMessage, layout = "umbrella", nodes, onNodeSelect, scopeLabel, statusLabel, title, layoutScope, layoutBinding }: GraphExplorerProps) {
  const { format, t } = useI18n();
  const canvasRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<HTMLDivElement>(null);
  const panRef = useRef({ x: 0, y: 0 });
  
  const [zoom, setZoom] = useState(1);
  const zoomRef = useRef(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [selected, setSelected] = useState<{ id: string; type: "edge" | "node" } | null>(null);
  const [draggingCanvas, setDraggingCanvas] = useState(false);
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const graphLayout = useGraphLayout(nodes, edges, layoutScope, layoutBinding);
  const positionScope = layoutScope ?? "standalone";
  const [manualScope, setManualScope] = useState(positionScope);
  const [nodePositions, setNodePositions] = useState<Record<string, { x: number; y: number }>>({});
  const canvasDrag = useRef<{ moved: boolean; originX: number; originY: number; pointerId: number; startX: number; startY: number } | null>(null);
  const nodeDrag = useRef<{ id: string; moved: boolean; originX: number; originY: number; pointerId: number; startX: number; startY: number } | null>(null);
  const suppressCanvasClick = useRef(false);
  const suppressNodeClick = useRef(false);
  const positionedNodes = useMemo(
    () => nodes.map((node) => ({ ...node, ...(graphLayout.positions[node.id] ?? {}), ...(manualScope === positionScope ? nodePositions[node.id] ?? {} : {}) })),
    [nodePositions, nodes, graphLayout.positions, manualScope, positionScope]
  );
  const zoomBand = semanticZoomBand(zoom);
  const visualScale = visualScaleForZoom(zoom);
  const visibleNodes = useMemo<VisibleGraphExplorerNode[]>(() => {
    const selectedNodeId = selected?.type === "node" ? selected.id : null;
    return positionedNodes.flatMap((node) => {
      const visibility = nodeVisibilityAtZoom(node, zoom, selectedNodeId);
      return visibility.visible ? [{ ...node, isHint: visibility.hint }] : [];
    });
  }, [positionedNodes, selected, zoom]);
  const { edgeById, nodeById, relatedEdgeIds, relatedNodeIds } = useRelationMap(visibleNodes, edges, selected);
  const selectedNode = selected?.type === "node" ? nodeById.get(selected.id) ?? null : null;
  const selectedEdge = selected?.type === "edge" ? edgeById.get(selected.id) ?? null : null;
  const selectedSource = selectedEdge ? nodeById.get(selectedEdge.source) : null;
  const selectedTarget = selectedEdge ? nodeById.get(selectedEdge.target) : null;
  const detailLevel = zoomBand === "structure" ? t("graphLayerStructure") : zoomBand === "chunk" ? t("graphLayerFocus") : t("graphLayerDetail");

  useEffect(() => {
    // Scope transitions clear interaction state; input-reference changes do not.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelected(null); setPan({ x: 0, y: 0 }); panRef.current = { x: 0, y: 0 };
    setZoom(1); zoomRef.current = 1;
    canvasDrag.current = null; nodeDrag.current = null;
    setDraggingCanvas(false); setDraggingNodeId(null);
    setNodePositions({}); setManualScope(positionScope);
  }, [positionScope]);

  function changeZoom(nextZoom: number) {
    const bounded = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM);
    zoomRef.current = bounded;
    setZoom(bounded);
  }

  function reset() {
    setPan({ x: 0, y: 0 });
    panRef.current = { x: 0, y: 0 };
    setZoom(1);
    zoomRef.current = 1;
    if (sceneRef.current) {
      sceneRef.current.style.transform = `translate(0px, 0px) scale(${visualScaleForZoom(1)})`;
    }
    setSelected(null);
    
    setNodePositions({});
    setManualScope(positionScope);
  }

  function handleWheel(event: WheelEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    // Use multiplicative scaling for smoother zooming at small zoom levels
    const zoomFactor = Math.exp(event.deltaY * -0.002);
    changeZoom(zoomRef.current * zoomFactor);
  }

  function startCanvasDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    canvasDrag.current = { moved: false, originX: pan.x, originY: pan.y, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY };
    suppressCanvasClick.current = false;
    setDraggingCanvas(true);
  }

  function moveCanvas(event: PointerEvent<HTMLDivElement>) {
    const drag = canvasDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - drag.startX;
    const deltaY = event.clientY - drag.startY;
    if (Math.hypot(deltaX, deltaY) > 4) drag.moved = true;
    const bounds = event.currentTarget.getBoundingClientRect();
    const newX = clamp(drag.originX + deltaX, -bounds.width * 5, bounds.width * 5);
    const newY = clamp(drag.originY + deltaY, -bounds.height * 5, bounds.height * 5);
    panRef.current = { x: newX, y: newY };
    if (sceneRef.current) {
      sceneRef.current.style.transform = `translate(${newX}px, ${newY}px) scale(${visualScaleForZoom(zoomRef.current)})`;
    }
  }

  function stopCanvasDrag(event: PointerEvent<HTMLDivElement>) {
    const drag = canvasDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    suppressCanvasClick.current = drag.moved;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (drag.moved) setPan(panRef.current);
    canvasDrag.current = null;
    setDraggingCanvas(false);
  }

  function startNodeDrag(event: PointerEvent<HTMLButtonElement>, node: GraphExplorerNode) {
    if (event.button !== 0) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    const position = manualScope === positionScope ? nodePositions[node.id] ?? graphLayout.positions[node.id] ?? { x: node.x, y: node.y } : graphLayout.positions[node.id] ?? { x: node.x, y: node.y };
    nodeDrag.current = { id: node.id, moved: false, originX: position.x, originY: position.y, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY };
    suppressNodeClick.current = false;
    setDraggingNodeId(node.id);
  }

  function moveNode(event: PointerEvent<HTMLButtonElement>) {
    event.stopPropagation();
    const drag = nodeDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = (event.clientX - drag.startX) / visualScaleForZoom(zoomRef.current);
    const deltaY = (event.clientY - drag.startY) / visualScaleForZoom(zoomRef.current);
    if (Math.hypot(deltaX, deltaY) > 4) drag.moved = true;
    const newX = drag.originX + deltaX;
    const newY = drag.originY + deltaY;
    setNodePositions((current) => ({
      ...(manualScope === positionScope ? current : {}),
      [drag.id]: {
        x: newX,
        y: newY
      }
    }));
    setManualScope(positionScope);
  }

  function stopNodeDrag(event: PointerEvent<HTMLButtonElement>) {
    event.stopPropagation();
    const drag = nodeDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    suppressNodeClick.current = drag.moved;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    
    nodeDrag.current = null;
    setDraggingNodeId(null);
  }

  function directNeighbors(nodeId: string) {
    return edges
      .flatMap((edge) => edge.source === nodeId ? [edge.target] : edge.target === nodeId ? [edge.source] : [])
      .map((id) => nodeById.get(id))
      .filter((node): node is GraphExplorerNode => Boolean(node));
  }

  return (
    <section data-graph-layout-state={graphLayout.state} className={`graph-explorer graph-explorer-layout-${layout}`} data-graph-explorer="true" data-graph-layout={layout}>
      <div className="graph-explorer-left">
        <header className="graph-explorer-toolbar">
          <div className="graph-explorer-heading">
            <Network size={18} />
            <div>
              <strong>{title}</strong>
              <span>{scopeLabel}</span>
            </div>
          </div>
          <div className="graph-explorer-layer" aria-label={t("graphDetailMetadata")}>
            <span>{detailLevel}</span>
            {statusLabel ? <em>{statusLabel}</em> : null}
          </div>
          <div className="graph-explorer-zoom" aria-label={t("graphExplorerZoomControls")}>
            <button aria-label={t("graphZoomOut")} disabled={zoom <= MIN_ZOOM} onClick={() => changeZoom(zoom * 0.8)} type="button"><ZoomOut size={16} /></button>
            <button aria-label={t("graphZoomIn")} disabled={zoom >= MAX_ZOOM} onClick={() => changeZoom(zoom * 1.25)} type="button"><ZoomIn size={16} /></button>
            <button aria-label={t("graphReset")} disabled={!selected && pan.x === 0 && pan.y === 0 && zoom === 1 && Object.keys(nodePositions).length === 0 && Object.keys(graphLayout.positions).length === 0} onClick={reset} type="button"><RotateCcw size={16} /></button>
          </div>
        </header>

        {graphLayout.state === "pending" ? <div className="graph-layout-feedback"><FeedbackMessage title={t("graphLayoutPending")} tone="info" /></div> : graphLayout.state === "error" ? <div className="graph-layout-feedback"><FeedbackMessage title={t("graphLayoutFailed")} tone="error" actions={<button className="action-button secondary" onClick={graphLayout.retry} type="button"><RotateCcw size={14} />{t("graphLayoutRetry")}</button>} /></div> : null}

        <div
          aria-label={t("graphCanvasAria")}
          className={`graph-explorer-canvas${draggingCanvas ? " is-dragging" : ""}`}
          data-graph-canvas="relationship"
          onClick={() => {
            if (suppressCanvasClick.current) { suppressCanvasClick.current = false; return; }
            setSelected(null);
          }}
          onPointerCancel={stopCanvasDrag}
          onPointerDown={startCanvasDrag}
          onPointerLeave={stopCanvasDrag}
          onPointerMove={moveCanvas}
          onPointerUp={stopCanvasDrag}
          onWheel={handleWheel}
          ref={canvasRef}
          role="application"
          tabIndex={0}
        >
          {visibleNodes.length ? (
            <div ref={sceneRef} className="graph-explorer-scene" data-zoom-band={zoomBand} style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${visualScale})` }}>
              <svg aria-label={t("graphEdgesAria")} className="graph-explorer-edges" role="group" style={{ overflow: "visible" }}>
                <defs>
                  <marker id="arrowhead" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">
                    <polygon points="0 0, 6 2, 0 4" fill="var(--cool-gray)" />
                  </marker>
                  <marker id="arrowhead-selected" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">
                    <polygon points="0 0, 6 2, 0 4" fill="var(--deep-green)" />
                  </marker>
                  <marker id="arrowhead-tagged_as" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">
                    <polygon points="0 0, 6 2, 0 4" fill="#475569" />
                  </marker>
                  <marker id="arrowhead-semantic" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">
                    <polygon points="0 0, 6 2, 0 4" fill="var(--gold)" />
                  </marker>
                  <marker id="arrowhead-source" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">
                    <polygon points="0 0, 6 2, 0 4" fill="rgba(46, 58, 66, 0.4)" />
                  </marker>
                  <marker id="arrowhead-contains" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">
                    <polygon points="0 0, 6 2, 0 4" fill="var(--calm-green)" />
                  </marker>
                  <filter x="-0.1" y="-0.2" width="1.2" height="1.4" id="solidBg">
                    <feFlood floodColor="rgba(252, 253, 251, 0.85)" result="bg" />
                    <feComposite in="SourceGraphic" in2="bg" operator="over" />
                  </filter>
                </defs>
                {edges.map((edge) => {
                  const source = nodeById.get(edge.source);
                  const target = nodeById.get(edge.target);
                  if (!source || !target) return null;
                  const active = (selected?.type === "edge" && selected.id === edge.id) || (selected?.type === "node" && relatedEdgeIds.has(edge.id));
                  const related = !selected || relatedEdgeIds.has(edge.id);
                  const hintEdge = Boolean(source.isHint || target.isHint);
                  return (
                    <path
                      aria-label={format("graphRelationSelectAria", { source: source.title, target: target.title })}
                      className={`${active ? "is-selected" : ""}${related ? " is-related" : " is-muted"}${hintEdge ? " is-hint-edge" : ""} relation-${edge.relation}`}
                      d={edgePath(source, target)}
                      key={edge.id}
                      markerEnd={edge.relation === "tagged_as" ? "url(#arrowhead-tagged_as)" : (active ? "url(#arrowhead-selected)" : (["semantic", "source", "contains"].includes(edge.relation) ? `url(#arrowhead-${edge.relation})` : "url(#arrowhead)"))}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelected({ id: edge.id, type: "edge" });
                      }}
                      onKeyDown={(event) => {
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        setSelected({ id: edge.id, type: "edge" });
                      }}
                      role="button"
                      tabIndex={0}
                    />
                  );
                })}
                {edges.map((edge) => {
                  if (edge.showLabel === false) return null;
                  const source = nodeById.get(edge.source);
                  const target = nodeById.get(edge.target);
                  if (!source || !target) return null;
                  const active = (selected?.type === "edge" && selected.id === edge.id) || (selected?.type === "node" && relatedEdgeIds.has(edge.id));
                  const related = selected?.type === "node" && relatedEdgeIds.has(edge.id);
                  if (!active && !related) return null;
                  const position = edgeLabelPosition(source, target);
                  return (
                    <g key={`${edge.id}-label`} className={`graph-explorer-edge-label relation-${edge.relation}${active ? " is-selected" : ""}${related ? " is-related" : " is-muted"}`}>
                      <rect
                        x={position.x - (edge.label.length * 3.5 + 4)}
                        y={position.y - 12}
                        width={edge.label.length * 7 + 8}
                        height="16"
                        rx="4"
                        fill="rgba(252, 253, 251, 0.95)"
                        stroke="rgba(214, 224, 229, 0.5)"
                      />
                      <text
                        aria-hidden="true"
                        x={position.x}
                        y={position.y}
                      >
                        {edge.label}
                      </text>
                    </g>
                  );
                })}
              </svg>
              {visibleNodes.map((node) => {
                const active = selected?.type === "node" && selected.id === node.id;
                const muted = Boolean(selected && !relatedNodeIds.has(node.id));
                return (
                  <button
                    aria-label={`${t(nodeTypeKey(node.kind))}: ${node.title}`}
                    aria-pressed={active}
                    className={`graph-explorer-node node-${node.kind}${node.isHint ? " is-hint" : ""}${active ? " is-selected" : ""}${muted ? " is-muted" : ""}${draggingNodeId === node.id ? " is-dragging" : ""}`}
                    data-content-type={node.contentType}
                    data-graph-node-kind={node.kind}
                    data-semantic-layer={node.semanticLayer}
                    key={node.id}
                    onClick={(event) => {
                      event.stopPropagation();
                      if (suppressNodeClick.current) { suppressNodeClick.current = false; return; }
                      setSelected({ id: node.id, type: "node" });
                      onNodeSelect?.(node.id);
                    }}
                    onPointerCancel={stopNodeDrag}
                    onPointerDown={(event) => startNodeDrag(event, node)}
                    onPointerMove={moveNode}
                    onPointerUp={stopNodeDrag}
                    style={{ left: node.x, top: node.y }}
                    type="button"
                  >
                    <span className="graph-explorer-node-icon"><GraphNodeIcon contentType={node.contentType} kind={node.kind} /></span>
                    <span className="graph-explorer-node-copy">
                      <strong>{node.title}</strong>
                      {node.subtitle ? <small>{node.subtitle}</small> : null}
                    </span>
                    {node.groupCount ? <span className="graph-explorer-node-count">{node.groupCount}</span> : null}
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="graph-explorer-empty">
              <Info size={20} />
              <strong>{emptyMessage ?? t("graphExplorerEmpty")}</strong>
            </div>
          )}
        </div>
      </div>

      <aside className="graph-explorer-inspector" aria-live="polite" data-graph-inspector="true">
          <div className="graph-explorer-inspector-title">
            <Info size={17} />
            <strong>{t("graphDetailPanelTitle")}</strong>
          </div>
          {selectedNode ? (
            <div className="graph-explorer-inspector-content">
              <div className="graph-explorer-inspector-subject">
                <span className={`node-kind-dot dot-${selectedNode.kind}`}><GraphNodeIcon contentType={selectedNode.contentType} kind={selectedNode.kind} /></span>
                <div>
                  <strong>{selectedNode.title}</strong>
                  <small>{t(nodeTypeKey(selectedNode.kind))}{selectedNode.subtitle ? ` · ${selectedNode.subtitle}` : ""}</small>
                </div>
              </div>
              <dl>
                {selectedNode.kind === "chunk" ? <div><dt>{t("graphDetailChunkNumber")}</dt><dd data-graph-chunk-number="true">{typeof selectedNode.chunkIndex === "number" ? `#${selectedNode.chunkIndex}` : t("graphDetailUnavailable")}</dd></div> : null}
                {selectedNode.kind === "chunk" ? (
                  <div>
                    <dt>{t("graphDetailChunkFullContent")}</dt>
                    <dd aria-label={t("graphDetailChunkFullContent")} className="graph-explorer-chunk-content" data-graph-chunk-content="true" role="region" tabIndex={0}>
                      {selectedNode.chunkContent !== undefined || selectedNode.chunkDisplayMarkdown || selectedNode.chunkMarkdownContent ? (
                        <ChunkMarkdownView
                          chunk={{
                            content: selectedNode.chunkContent,
                            display_markdown: selectedNode.chunkDisplayMarkdown,
                            markdown_content: selectedNode.chunkMarkdownContent,
                          }}
                          className="graph-chunk-markdown"
                        />
                      ) : t("graphDetailChunkContentUnavailable")}
                    </dd>
                  </div>
                ) : null}
                {selectedNode.technicalId ? <div><dt>{t("graphDetailTechnicalId")}</dt><dd>{selectedNode.technicalId}</dd></div> : null}
                {selectedNode.contentType ? <div><dt>{t("graphExplorerContentType")}</dt><dd>{t(contentTypeLabelKeys[selectedNode.contentType])}</dd></div> : null}
                {selectedNode.meta?.map((item) => <div key={`${item.label}-${item.value}`}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}
              </dl>
              <section>
                <h3>{t("graphDetailNeighbors")}</h3>
                <div className="graph-explorer-chip-list">
                  {directNeighbors(selectedNode.id).length ? directNeighbors(selectedNode.id).map((node) => (
                    <button key={node.id} onClick={() => { setSelected({ id: node.id, type: "node" }); onNodeSelect?.(node.id); }} type="button">{node.title}</button>
                  )) : <span>{t("graphExplorerNoNeighbors")}</span>}
                </div>
              </section>
            </div>
          ) : selectedEdge && selectedSource && selectedTarget ? (
            <div className="graph-explorer-inspector-content">
              <div className="graph-explorer-inspector-subject">
                <span className="node-kind-dot dot-edge"><Link2 size={16} /></span>
                <div>
                  <strong>{selectedEdge.label}</strong>
                  <small>{selectedSource.title}{" -> "}{selectedTarget.title}</small>
                </div>
              </div>
              <dl>
                <div><dt>{t("graphDetailRelationship")}</dt><dd>{selectedEdge.label}</dd></div>
                <div><dt>{t("graphDetailSource")}</dt><dd>{selectedSource.title}</dd></div>
                <div><dt>{t("graphDetailTarget")}</dt><dd>{selectedTarget.title}</dd></div>
                {selectedEdge.meta?.map((item) => <div key={`${item.label}-${item.value}`}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}
              </dl>
            </div>
          ) : (
            <div className="graph-explorer-inspector-empty">
              <Network size={22} />
              <strong>{t("graphExplorerInspectorEmptyTitle")}</strong>
              <p>{t("graphDetailEmpty")}</p>
              <dl>
                <div><dt>{t("graphExplorerNodeCount")}</dt><dd>{nodes.length}</dd></div>
                <div><dt>{t("graphExplorerEdgeCount")}</dt><dd>{edges.length}</dd></div>
              </dl>
            </div>
          )}
        </aside>
    </section>
  );
}
