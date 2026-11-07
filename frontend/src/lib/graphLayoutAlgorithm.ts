import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import { GRAPH_HEIGHT, GRAPH_WIDTH, type LayoutNode, type LayoutSnapshot, type GraphPositions } from "./graphLayoutProtocol";

type SimNode = LayoutNode & SimulationNodeDatum;
type SimLink = SimulationLinkDatum<SimNode>;

/** Executed by the module Worker; keep the original force settings and 400 ticks. */
export function computeGraphPositions(snapshot: LayoutSnapshot): GraphPositions {
  const hasProject = snapshot.nodes.some(node => node.kind === "project");
  const nodes: SimNode[] = snapshot.nodes.map(node => ({ ...node,
    ...(hasProject ? node.kind === "project" : node.id === "document") ? { fx: GRAPH_WIDTH / 2, fy: GRAPH_HEIGHT / 2 } : {}
  }));
  const links: SimLink[] = snapshot.edges.map(edge => ({ source: edge.source, target: edge.target }));
  const byId = new Map(nodes.map(node => [node.id, node]));
  const simulation = forceSimulation(nodes)
    .force("link", forceLink<SimNode, SimLink>(links).id(node => node.id).distance(link => {
      const source = typeof link.source === "object" ? link.source : byId.get(String(link.source));
      const target = typeof link.target === "object" ? link.target : byId.get(String(link.target));
      if (source?.kind === "project" || target?.kind === "project") return 380;
      if (source?.kind === "document" || target?.kind === "document") return 270;
      if ((source?.kind === "tag" && target?.kind === "chunk") || (source?.kind === "chunk" && target?.kind === "tag")) return 150;
      return 190;
    }))
    .force("charge", forceManyBody<SimNode>().strength(node => node.kind === "project" ? -6200 : node.kind === "document" ? -3400 : node.kind === "group" ? -1600 : node.kind === "chunk" ? -1350 : -1150))
    .force("x", forceX<SimNode>(node => node.x).strength(node => node.kind === "project" ? 0.2 : node.semanticLayer ? 0.1 : 0.05))
    .force("y", forceY<SimNode>(node => node.y).strength(node => node.kind === "project" ? 0.2 : node.semanticLayer ? 0.1 : 0.05))
    .force("center", forceCenter(GRAPH_WIDTH / 2, GRAPH_HEIGHT / 2))
    .force("collide", forceCollide<SimNode>().radius(node => Math.max(node.width, node.height) * 0.5 * 1.85).iterations(4))
    .stop();
  try {
    for (let tick = 0; tick < 400; tick++) simulation.tick();
    return Object.fromEntries(nodes.map(node => [node.id, { x: node.x, y: node.y }]));
  } finally { simulation.stop(); }
}
