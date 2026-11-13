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
