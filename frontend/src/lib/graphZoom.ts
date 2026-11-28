export const MIN_GRAPH_ZOOM = 1;
export const MAX_GRAPH_ZOOM = 3;

export function boundedGraphZoom(value: number) {
  return Math.round(Math.min(MAX_GRAPH_ZOOM, Math.max(MIN_GRAPH_ZOOM, value)) * 10000) / 10000;
}

export function stepGraphZoom(value: number, direction: -1 | 1) {
  return boundedGraphZoom(value + direction * 0.05);
}

/** Semantic detail grows faster than geometry: the largest 160px node caps at 216px. */
export function graphVisualScale(zoom: number) {
  return 1 + (boundedGraphZoom(zoom) - 1) * 0.175;
}

/**
 * LF495-01: scale that fits the whole graph scene inside the canvas (never enlarges). The scene keeps
 * a small margin so outer nodes are not flush with the canvas edge.
 */
export function graphSceneFitScale(canvasWidth: number, canvasHeight: number, sceneWidth: number, sceneHeight: number, margin = 24): number {
  if (canvasWidth <= 0 || canvasHeight <= 0) return 1;
  const fit = Math.min(1, (canvasWidth - margin) / sceneWidth, (canvasHeight - margin) / sceneHeight);
  return Math.round(Math.max(0.3, fit) * 1000) / 1000;
}
