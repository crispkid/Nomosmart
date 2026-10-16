import { computeGraphPositions } from "../lib/graphLayoutAlgorithm";
import { GRAPH_LAYOUT_VERSION, type LayoutRequest, type LayoutReply } from "../lib/graphLayoutProtocol";

const scope = self as unknown as { onmessage: ((event: MessageEvent<LayoutRequest>) => void) | null; postMessage: (reply: LayoutReply) => void };
scope.onmessage = ({ data }) => {
  try {
    if (data.snapshot.version !== GRAPH_LAYOUT_VERSION) throw new Error("layout_version_mismatch");
    scope.postMessage({ id: data.id, positions: computeGraphPositions(data.snapshot) });
  } catch { scope.postMessage({ id: data.id, error: "graph_layout_failed" }); }
};
