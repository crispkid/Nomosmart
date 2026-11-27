"use client";

import { boundedGraphZoom, graphSceneFitScale, stepGraphZoom } from "@/lib/graphZoom";
import { type PointerEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { GRAPH_HEIGHT, GRAPH_WIDTH } from "@/lib/graphLayoutProtocol";
import { useGraphLayout } from "@/lib/useGraphLayout";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { Info, Link2, Network, RotateCcw, SlidersHorizontal, ZoomIn, ZoomOut } from "lucide-react";
import { ChunkMarkdownView } from "@/components/ChunkMarkdownView";
import { useI18n } from "@/lib/i18nClient";
import { formatShortDate } from "@/lib/dateFormat";
import { GraphExplorerFilters } from "./graphExplorer/GraphExplorerFilters";
import { type GraphExplorerNode, type GraphExplorerEdge, MIN_ZOOM, MAX_ZOOM, type VisibleGraphExplorerNode, type GraphPanExtent, contentTypeLabelKeys, clamp, semanticZoomBand, visualScaleForZoom, constrainGraphPan, nodeVisibilityAtZoom, nodeDimensions, edgePath, edgeLabelPosition, nodeTypeKey, GraphNodeIcon, useRelationMap, applyGraphFilters, defaultGraphFilters, graphFiltersActive, type GraphFilters } from "./graphExplorer/graphExplorerModel";

export type { GraphExplorerNode, GraphExplorerEdge } from "./graphExplorer/graphExplorerModel";

/** CHG-495 UIRD-API-005: totals of the whole published graph, before the node limit applies. */
export type GraphExplorerTotals = { edgeCount?: number | null; nodeCount?: number | null; typeCounts?: Record<string, number>; updatedAt?: string | null };

type GraphExplorerProps = {
  edges: GraphExplorerEdge[];
  emptyMessage?: string;
  /** CHG-495 M23: show the left filter panel (project graph). */
  filterable?: boolean;
  layout?: "umbrella";
  layoutScope?: string;
  layoutBinding?: string | null;
  nodes: GraphExplorerNode[];
  onNodeSelect?: (nodeId: string) => void;
  scopeLabel: string;
  statusLabel?: string;
  title: string;
  totals?: GraphExplorerTotals;
};

// CHG-495 K140: level buttons jump to the zoom where that level of detail starts; wheel and +/- zoom still work.
const zoomLevels = [{ band: "structure", key: "graphLayerStructure", zoom: 1 }, { band: "chunk", key: "graphLayerFocus", zoom: 1.5 }, { band: "detail", key: "graphLayerDetail", zoom: 2 }] as const;

export function GraphExplorer({ edges, emptyMessage, filterable = false, layout = "umbrella", nodes, onNodeSelect, scopeLabel, statusLabel, title, totals, layoutScope, layoutBinding }: GraphExplorerProps) {
  const { format, locale, t } = useI18n();
  const filterPanelId = useId();
  const [filters, setFilters] = useState<GraphFilters>(defaultGraphFilters);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const canvasRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<HTMLDivElement>(null);
  const panRef = useRef({ x: 0, y: 0 });
  const panExtentRef = useRef<GraphPanExtent | null>(null);
  
  const [zoom, setZoom] = useState(1);
  const zoomRef = useRef(1);
  // LF495-01: the fixed scene shrinks to fit a narrow canvas (sidebar + filter column), so every node
  // stays visible and clickable at the default view; zoom bands still follow the semantic zoom.
  const [fitScale, setFitScale] = useState(1);
  const fitScaleRef = useRef(1);
  const sceneScale = (value: number) => visualScaleForZoom(value) * fitScaleRef.current;
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
  const visualScale = visualScaleForZoom(zoom) * fitScale;
  const selectedNodeId = selected?.type === "node" ? selected.id : null;
  const filtered = useMemo(() => applyGraphFilters(positionedNodes, edges, filters, selectedNodeId), [edges, filters, positionedNodes, selectedNodeId]);
  const shownEdges = filtered.edges;
  const visibleNodes = useMemo<VisibleGraphExplorerNode[]>(() => {
    return filtered.nodes.flatMap((node) => {
      const visibility = nodeVisibilityAtZoom(node, zoom, selectedNodeId);
      return visibility.visible ? [{ ...node, isHint: visibility.hint }] : [];
    });
  }, [filtered.nodes, selectedNodeId, zoom]);
  const panExtent = useMemo<GraphPanExtent | null>(() => {
    if (!visibleNodes.length) return null;
    const extent = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity, nodeWidth: 0, nodeHeight: 0 };
    for (const node of visibleNodes) {
      const { w, h } = nodeDimensions(node);
      extent.minX = Math.min(extent.minX, node.x);
      extent.maxX = Math.max(extent.maxX, node.x);
      extent.minY = Math.min(extent.minY, node.y);
      extent.maxY = Math.max(extent.maxY, node.y);
      extent.nodeWidth = Math.max(extent.nodeWidth, w);
      extent.nodeHeight = Math.max(extent.nodeHeight, h);
    }
    return extent;
  }, [visibleNodes]);
  const { edgeById, nodeById, relatedEdgeIds, relatedNodeIds } = useRelationMap(visibleNodes, shownEdges, selected);
  const selectedNode = selected?.type === "node" ? nodeById.get(selected.id) ?? null : null;
  const selectedEdge = selected?.type === "edge" ? edgeById.get(selected.id) ?? null : null;
  const selectedSource = selectedEdge ? nodeById.get(selectedEdge.source) : null;
  const selectedTarget = selectedEdge ? nodeById.get(selectedEdge.target) : null;
  const activeLevel = zoomBand === "structure" || zoomBand === "chunk" ? zoomBand : "detail";
  const totalNodes = Math.max(totals?.nodeCount ?? 0, nodes.length);
  const summaryParts = [
    format("graphShownOfTotal", { shown: visibleNodes.length, total: totalNodes }),
    typeof totals?.edgeCount === "number" ? format("graphTotalEdges", { count: totals.edgeCount }) : null,
    totals?.updatedAt ? format("graphUpdatedOn", { date: formatShortDate(totals.updatedAt, locale) }) : null
  ].filter(Boolean).join(" · ");

  useEffect(() => { panExtentRef.current = panExtent; }, [panExtent]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => {
      const fit = graphSceneFitScale(canvas.clientWidth, canvas.clientHeight, GRAPH_WIDTH, GRAPH_HEIGHT);
      if (fit !== fitScaleRef.current) { fitScaleRef.current = fit; setFitScale(fit); return; }
      const previous = panRef.current;
      const next = constrainGraphPan(previous, panExtentRef.current, canvas.clientWidth, canvas.clientHeight, visualScale);
      if (next.x === previous.x && next.y === previous.y) return;
      panRef.current = next;
      setPan(next);
      if (sceneRef.current) sceneRef.current.style.transform = `translate(${next.x}px, ${next.y}px) scale(${visualScale})`;
      const drag = canvasDrag.current;
      if (drag) {
        drag.originX += next.x - previous.x;
        drag.originY += next.y - previous.y;
      }
    });
    observer.observe(canvas);
    return () => observer.disconnect();
    // Manual node drags update the next pan's bounds without moving the canvas.
  }, [graphLayout.positions, nodes, positionScope, selected, visualScale]);

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
    const bounded = boundedGraphZoom(nextZoom);
    zoomRef.current = bounded;
    setZoom(bounded);
  }

  function reset() {
    setPan({ x: 0, y: 0 });
    panRef.current = { x: 0, y: 0 };
    setZoom(1);
    zoomRef.current = 1;
    if (sceneRef.current) {
      sceneRef.current.style.transform = `translate(0px, 0px) scale(${sceneScale(1)})`;
    }
    setSelected(null);
    
    setNodePositions({});
    setManualScope(positionScope);
  }

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    function handleWheel(event: globalThis.WheelEvent) {
      event.preventDefault();
      event.stopPropagation();
      const units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas!.clientHeight : 1;
      const delta = clamp(event.deltaY * units, -100, 100);
      const bounded = boundedGraphZoom(zoomRef.current * Math.exp(delta * -0.0005));
      zoomRef.current = bounded;
      setZoom(bounded);
    }
    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", handleWheel);
  }, []);

  function startCanvasDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    canvasDrag.current = { moved: false, originX: panRef.current.x, originY: panRef.current.y, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY };
    suppressCanvasClick.current = false;
    setDraggingCanvas(true);
  }

  function moveCanvas(event: PointerEvent<HTMLDivElement>) {
    const drag = canvasDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - drag.startX;
    const deltaY = event.clientY - drag.startY;
    if (Math.hypot(deltaX, deltaY) > 4) drag.moved = true;
    const { x: newX, y: newY } = constrainGraphPan(
      { x: drag.originX + deltaX, y: drag.originY + deltaY }, panExtent,
      event.currentTarget.clientWidth, event.currentTarget.clientHeight, sceneScale(zoomRef.current)
    );
    panRef.current = { x: newX, y: newY };
    if (sceneRef.current) {
      sceneRef.current.style.transform = `translate(${newX}px, ${newY}px) scale(${sceneScale(zoomRef.current)})`;
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
    const deltaX = (event.clientX - drag.startX) / sceneScale(zoomRef.current);
    const deltaY = (event.clientY - drag.startY) / sceneScale(zoomRef.current);
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
    return shownEdges
      .flatMap((edge) => edge.source === nodeId ? [edge.target] : edge.target === nodeId ? [edge.source] : [])
      .map((id) => nodeById.get(id))
      .filter((node): node is GraphExplorerNode => Boolean(node));
  }

  return (
    <section data-graph-layout-state={graphLayout.state} className={`graph-explorer graph-explorer-layout-${layout}${filterable ? " has-filters" : ""}`} data-graph-explorer="true" data-graph-layout={layout}>
      {filterable ? <GraphExplorerFilters edges={edges} filters={filters} id={filterPanelId} nodes={nodes} onChange={setFilters} open={filtersOpen} typeTotals={totals?.typeCounts} /> : null}
      <div className="graph-explorer-left">
        <header className="graph-explorer-toolbar">
          <div className="graph-explorer-heading">
            <Network aria-hidden="true" size={18} />
            <div>
              <strong>{title}</strong>
              <span>{scopeLabel}</span>
            </div>
          </div>
          <div className="graph-explorer-layer">
            <div aria-label={t("graphLevelLabel")} className="ws-segmented graph-level-switch" role="group">
              {zoomLevels.map((level) => <button aria-pressed={activeLevel === level.band} key={level.band} onClick={() => changeZoom(level.zoom)} type="button">{t(level.key)}</button>)}
            </div>
            {statusLabel ? <em>{statusLabel}</em> : null}
          </div>
          <div className="graph-explorer-zoom" aria-label={t("graphExplorerZoomControls")}>
            {filterable ? <button aria-controls={filterPanelId} aria-expanded={filtersOpen} aria-label={t("graphFiltersTitle")} className={`graph-explorer-filter-toggle${graphFiltersActive(filters) ? " is-active" : ""}`} onClick={() => setFiltersOpen((open) => !open)} type="button"><SlidersHorizontal size={16} /></button> : null}
            <button aria-label={t("graphZoomOut")} disabled={zoom <= MIN_ZOOM} onClick={() => changeZoom(stepGraphZoom(zoom, -1))} type="button"><ZoomOut size={16} /></button>
            <output aria-label={format("graphZoomPercent", { percent: Math.round(zoom * 100) })} aria-live="polite">{Math.round(zoom * 100)}%</output>
            <button aria-label={t("graphZoomIn")} disabled={zoom >= MAX_ZOOM} onClick={() => changeZoom(stepGraphZoom(zoom, 1))} type="button"><ZoomIn size={16} /></button>
            <button aria-label={t("graphReset")} disabled={!selected && pan.x === 0 && pan.y === 0 && zoom === 1 && Object.keys(nodePositions).length === 0 && Object.keys(graphLayout.positions).length === 0} onClick={reset} type="button"><RotateCcw size={16} /></button>
          </div>
        </header>

        {graphLayout.state === "pending" ? <div className="graph-layout-feedback"><FeedbackMessage title={t("graphLayoutPending")} tone="info" /></div> : graphLayout.state === "error" ? <div className="graph-layout-feedback"><FeedbackMessage title={t("graphLayoutFailed")} tone="error" actions={<button className="action-button secondary" onClick={graphLayout.retry} type="button"><RotateCcw size={14} />{t("graphLayoutRetry")}</button>} /></div> : null}

        <div aria-label={t("graphLegendLabel")} className="graph-explorer-legend" role="list">
          {(["project", "document", "chunk", "tag", "group"] as const).map((kind) => <span className="graph-legend-item" key={kind} role="listitem"><span aria-hidden="true" className={`graph-filter-swatch swatch-${kind}`}><GraphNodeIcon kind={kind} /></span>{t(nodeTypeKey(kind))}</span>)}
          <span className="graph-legend-item" role="listitem"><span aria-hidden="true" className="graph-filter-line line-contains" />{t("graphLegendContains")}</span>
          <span className="graph-legend-item" role="listitem"><span aria-hidden="true" className="graph-filter-line line-tagged_as" />{t("graphRelationTaggedAs")}</span>
        </div>

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
          ref={canvasRef}
          role="application"
          tabIndex={0}
        >
          {visibleNodes.length ? (
            <div ref={sceneRef} className="graph-explorer-scene" data-zoom-band={zoomBand} style={{ width: GRAPH_WIDTH, height: GRAPH_HEIGHT, left: "50%", top: "50%", right: "auto", bottom: "auto", marginLeft: -GRAPH_WIDTH / 2, marginTop: -GRAPH_HEIGHT / 2, transform: `translate(${pan.x}px, ${pan.y}px) scale(${visualScale})` }}>
              <svg aria-label={t("graphEdgesAria")} className="graph-explorer-edges" role="group" style={{ overflow: "visible" }}>
                <defs>
                  {/* CHG-495 UIRD-001: arrowheads take theme colours from CSS (graph follows dark mode). */}
                  {["default", "selected", "tagged_as", "semantic", "source", "contains", "references", "supersedes"].map((name) => (
                    <marker className={`graph-arrowhead arrowhead-${name}`} id={name === "default" ? "arrowhead" : `arrowhead-${name}`} key={name} markerHeight="4" markerWidth="6" orient="auto" refX="5" refY="2">
                      <polygon points="0 0, 6 2, 0 4" />
                    </marker>
                  ))}
                </defs>
                {shownEdges.map((edge) => {
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
                      markerEnd={active ? "url(#arrowhead-selected)" : `url(#arrowhead-${edge.relation})`}
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
                {shownEdges.map((edge) => {
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
              <strong>{nodes.length && graphFiltersActive(filters) ? t("graphFiltersEmpty") : emptyMessage ?? t("graphExplorerEmpty")}</strong>
            </div>
          )}
        </div>
        <p className="graph-explorer-summary" aria-live="polite">{summaryParts}</p>
      </div>

      <aside className="graph-explorer-inspector" aria-live="polite" data-graph-inspector="true">
          <div className="graph-explorer-inspector-title">
            <Info aria-hidden="true" size={16} />
            <strong>{t("graphDetailPanelTitle")}</strong>
          </div>
          {selectedNode ? (
            <div className="graph-explorer-inspector-content">
              <div className={`graph-explorer-inspector-subject subject-${selectedNode.kind}`}>
                <span className={`node-kind-dot dot-${selectedNode.kind}`}><GraphNodeIcon contentType={selectedNode.contentType} kind={selectedNode.kind} /></span>
                <div>
                  <small className="graph-explorer-inspector-kind">{t(nodeTypeKey(selectedNode.kind))}</small>
                  <strong>{selectedNode.title}</strong>
                  {selectedNode.subtitle ? <small>{selectedNode.subtitle}</small> : null}
                </div>
              </div>
              <dl>
                {selectedNode.kind === "chunk" ? <div><dt>{t("graphDetailChunkNumber")}</dt><dd data-graph-chunk-number="true">{typeof selectedNode.chunkIndex === "number" ? `#${selectedNode.chunkIndex}` : t("graphDetailUnavailable")}</dd></div> : null}
                {selectedNode.contentType ? <div><dt>{t("graphExplorerContentType")}</dt><dd>{t(contentTypeLabelKeys[selectedNode.contentType])}</dd></div> : null}
                {selectedNode.meta?.map((item) => <div key={`${item.label}-${item.value}`}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}
              </dl>
              {selectedNode.kind === "chunk" ? (
                <section className="graph-explorer-inspector-section">
                  <h3>{t("graphDetailChunkFullContent")}</h3>
                  <div aria-label={t("graphDetailChunkFullContent")} className="graph-explorer-chunk-content" data-graph-chunk-content="true" role="region" tabIndex={0}>
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
                  </div>
                </section>
              ) : null}
              <section className="graph-explorer-inspector-section">
                <h3>{t("graphDetailNeighbors")}</h3>
                <div className="graph-explorer-chip-list">
                  {directNeighbors(selectedNode.id).length ? directNeighbors(selectedNode.id).map((node) => (
                    <button key={node.id} onClick={() => { setSelected({ id: node.id, type: "node" }); onNodeSelect?.(node.id); }} type="button"><span aria-hidden="true" className={`graph-chip-icon chip-${node.kind}`}><GraphNodeIcon contentType={node.contentType} kind={node.kind} /></span><span>{node.title}</span></button>
                  )) : <span>{t("graphExplorerNoNeighbors")}</span>}
                </div>
              </section>
              {selectedNode.technicalId ? (
                <details className="graph-explorer-technical">
                  <summary>{t("graphDetailTechnicalId")}</summary>
                  <code>{selectedNode.technicalId}</code>
                </details>
              ) : null}
            </div>
          ) : selectedEdge && selectedSource && selectedTarget ? (
            <div className="graph-explorer-inspector-content">
              <div className="graph-explorer-inspector-subject subject-edge">
                <span className="node-kind-dot dot-edge"><Link2 size={16} /></span>
                <div>
                  <small className="graph-explorer-inspector-kind">{t("graphDetailRelationship")}</small>
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
              <Network aria-hidden="true" size={22} />
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
