import type { GraphPositions } from "./graphLayoutProtocol";

type Budget = { entries: number; nodes: number };
const entries = new Map<string, GraphPositions>();
const cancellations = new Set<() => void>();
let session: string | null = null;
const counts = { dispatched: 0, completed: 0, cancelled: 0, hits: 0, failures: 0 };

export function graphCacheInteger(value: unknown, fallback: number, maximum: number): number {
  if (typeof value === "string" && /^\d+$/.test(value.trim())) value = Number(value);
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= maximum ? value : fallback;
}
export function graphCacheBudget(config: { graphLayoutCacheMaxEntries?: number; graphLayoutCacheMaxNodes?: number }): Budget {
  return { entries: graphCacheInteger(config.graphLayoutCacheMaxEntries, 8, 64), nodes: graphCacheInteger(config.graphLayoutCacheMaxNodes, 8000, 128000) };
}
function nodeCount() { return Array.from(entries.values()).reduce((sum, positions) => sum + Object.keys(positions).length, 0); }
function trim(budget: Budget) {
  while (entries.size && (entries.size > budget.entries || nodeCount() > budget.nodes || !budget.entries || !budget.nodes)) entries.delete(entries.keys().next().value!);
}
export function clearGraphLayoutSession() {
  session = null;
  entries.clear();
  for (const cancel of Array.from(cancellations)) cancel();
  cancellations.clear();
}
export function activateGraphLayoutSession(next: string | null) {
  if (session === next) return;
  clearGraphLayoutSession();
  session = next;
}
export function isGraphLayoutSession(owner: string) { return session === owner; }
export function getGraphLayoutCache(owner: string, key: string, budget: Budget): GraphPositions | null {
  trim(budget);
  if (!isGraphLayoutSession(owner) || !budget.entries || !budget.nodes) return null;
  const value = entries.get(key);
  if (!value) return null;
  entries.delete(key); entries.set(key, value); counts.hits++;
  return value;
}
export function putGraphLayoutCache(owner: string, key: string, positions: GraphPositions, budget: Budget) {
  if (!isGraphLayoutSession(owner) || !budget.entries || !budget.nodes || Object.keys(positions).length > budget.nodes) return;
  const copy = Object.fromEntries(Object.entries(positions).map(([id, point]) => [id, Object.freeze({ ...point })]));
  entries.delete(key); entries.set(key, Object.freeze(copy)); trim(budget);
}
export function registerGraphLayoutCancellation(cancel: () => void) { cancellations.add(cancel); return () => { cancellations.delete(cancel); }; }
export function countGraphLayout(event: keyof typeof counts) { counts[event]++; }
/** Content-free counters, also used to verify bounded resource lifetimes. */
export function graphLayoutDiagnostics() { return { ...counts, entries: entries.size, nodes: nodeCount(), active: cancellations.size }; }
