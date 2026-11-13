"use client";

import { boundedGraphZoom, stepGraphZoom } from "@/lib/graphZoom";
import { type PointerEvent, useEffect, useMemo, useRef, useState } from "react";
import { GRAPH_HEIGHT, GRAPH_WIDTH } from "@/lib/graphLayoutProtocol";
import { useGraphLayout } from "@/lib/useGraphLayout";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { Info, Link2, Network, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { ChunkMarkdownView } from "@/components/ChunkMarkdownView";
import { useI18n } from "@/lib/i18nClient";
import { type GraphExplorerNode, type GraphExplorerEdge, MIN_ZOOM, MAX_ZOOM, type VisibleGraphExplorerNode, type GraphPanExtent, contentTypeLabelKeys, clamp, semanticZoomBand, visualScaleForZoom, constrainGraphPan, nodeVisibilityAtZoom, nodeDimensions, edgePath, edgeLabelPosition, nodeTypeKey, GraphNodeIcon, useRelationMap } from "./graphExplorer/graphExplorerModel";

export type { GraphExplorerNodeKind, GraphExplorerContentType, GraphExplorerSemanticLayer, GraphExplorerMeta, GraphExplorerNode, GraphExplorerEdge } from "./graphExplorer/graphExplorerModel";

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

export function GraphExplorer({ edges, emptyMessage, layout = "umbrella", nodes, onNodeSelect, scopeLabel, statusLabel, title, layoutScope, layoutBinding }: GraphExplorerProps) {
  const { format, t } = useI18n();
  const canvasRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<HTMLDivElement>(null);
  const panRef = useRef({ x: 0, y: 0 });
  const panExtentRef = useRef<GraphPanExtent | null>(null);
  
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
  const { edgeById, nodeById, relatedEdgeIds, relatedNodeIds } = useRelationMap(visibleNodes, edges, selected);
  const selectedNode = selected?.type === "node" ? nodeById.get(selected.id) ?? null : null;
  const selectedEdge = selected?.type === "edge" ? edgeById.get(selected.id) ?? null : null;
  const selectedSource = selectedEdge ? nodeById.get(selectedEdge.source) : null;
  const selectedTarget = selectedEdge ? nodeById.get(selectedEdge.target) : null;
  const detailLevel = zoomBand === "structure" ? t("graphLayerStructure") : zoomBand === "chunk" ? t("graphLayerFocus") : t("graphLayerDetail");

  useEffect(() => { panExtentRef.current = panExtent; }, [panExtent]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => {
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
      sceneRef.current.style.transform = `translate(0px, 0px) scale(${visualScaleForZoom(1)})`;
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
      event.currentTarget.clientWidth, event.currentTarget.clientHeight, visualScaleForZoom(zoomRef.current)
    );
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
            <button aria-label={t("graphZoomOut")} disabled={zoom <= MIN_ZOOM} onClick={() => changeZoom(stepGraphZoom(zoom, -1))} type="button"><ZoomOut size={16} /></button>
            <output aria-label={format("graphZoomPercent", { percent: Math.round(zoom * 100) })} aria-live="polite">{Math.round(zoom * 100)}%</output>
            <button aria-label={t("graphZoomIn")} disabled={zoom >= MAX_ZOOM} onClick={() => changeZoom(stepGraphZoom(zoom, 1))} type="button"><ZoomIn size={16} /></button>
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
          ref={canvasRef}
          role="application"
          tabIndex={0}
        >
          {visibleNodes.length ? (
            <div ref={sceneRef} className="graph-explorer-scene" data-zoom-band={zoomBand} style={{ width: GRAPH_WIDTH, height: GRAPH_HEIGHT, left: "50%", top: "50%", right: "auto", bottom: "auto", marginLeft: -GRAPH_WIDTH / 2, marginTop: -GRAPH_HEIGHT / 2, transform: `translate(${pan.x}px, ${pan.y}px) scale(${visualScale})` }}>
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
