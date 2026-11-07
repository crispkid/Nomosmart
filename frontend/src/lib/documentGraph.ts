export type GraphNodeType = "document" | "chunk" | "tag";
export type GraphContentType = "text" | "image" | "table" | "chart";

export const CHUNK_GRAPH_PREVIEW_LENGTH = 24;

function graphemeSegments(value: string) {
  const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });
  return Array.from(segmenter.segment(value), ({ segment }) => segment);
}

export function chunkContentPreview(content: string | null | undefined) {
  const normalized = typeof content === "string" ? content.trim().replace(/\s+/gu, " ") : "";
  if (!normalized) return null;

  const graphemes = graphemeSegments(normalized);
  const preview = graphemes.slice(0, CHUNK_GRAPH_PREVIEW_LENGTH).join("");
  return graphemes.length > CHUNK_GRAPH_PREVIEW_LENGTH ? `${preview}…` : preview;
}

export function chunkGraphTitle(content: string | null | undefined, fallback: string) {
  return chunkContentPreview(content) ?? fallback;
}

export type DocumentGraphTag = {
  id: string;
  text: string;
  source?: string | null;
};

export type DocumentGraphChunk = {
  chunkIndex: number;
  content: string;
  displayMarkdown?: string | null;
  id: string;
  markdownContent?: string | null;
  type: GraphContentType;
  sourceLabel: string;
  tags: string[];
  tagDetails?: DocumentGraphTag[];
};

export type DocumentGraphNode = {
  id: string;
  label: string;
  detail: string;
  type: GraphNodeType;
  technicalId?: string;
  contentType?: GraphContentType;
  x: number;
  y: number;
};

export type DocumentGraphEvidence = {
  documentTitle: string;
  version: string;
  chunks: DocumentGraphChunk[];
  documentTags?: DocumentGraphTag[];
};

function radialPosition(index: number, count: number, radius: number, phase = -Math.PI / 2) {
  const angle = phase + (Math.PI * 2 * index) / Math.max(1, count);
  return {
    x: 50 + Math.cos(angle) * radius,
    y: 50 + Math.sin(angle) * radius
  };
}

function chunkNodeId(chunkId: string) {
  return `chunk-${chunkId.toLowerCase().replaceAll(/[^a-z0-9-]/g, "-")}`;
}

function graphTagKey(tag: DocumentGraphTag | string) {
  const id = typeof tag === "string" ? "" : tag.id.trim();
  if (id) return `id:${id}`;
  const text = typeof tag === "string" ? tag : tag.text;
  return `text:${text.trim().toLowerCase()}`;
}

function graphTagNodeId(key: string) {
  return `tag-${key.toLowerCase().replaceAll(/[^a-z0-9-]/g, "-")}`;
}

function chunkGraphTags(chunk: DocumentGraphChunk): DocumentGraphTag[] {
  if (chunk.tagDetails?.length) return chunk.tagDetails.filter((tag) => tag.text.trim());
  return chunk.tags.filter((tag) => tag.trim()).map((tag) => ({ id: "", text: tag }));
}

function tagSourceLabel(tag: DocumentGraphTag) {
  if (tag.source === "llm") return "LLM";
  if (tag.source === "manual") return "Manual";
  if (tag.source === "rule") return "Rule";
  if (tag.source === "legacy") return "Legacy";
  return null;
}

export function buildDocumentGraph(evidence: DocumentGraphEvidence) {
  const tagMap = new Map<string, { tag: DocumentGraphTag; documentLevel: boolean; chunkIds: Set<string> }>();

  for (const tag of evidence.documentTags ?? []) {
    if (!tag.text.trim()) continue;
    const key = graphTagKey(tag);
    tagMap.set(key, { tag, documentLevel: true, chunkIds: new Set() });
  }

  for (const chunk of evidence.chunks) {
    for (const tag of chunkGraphTags(chunk)) {
      const key = graphTagKey(tag);
      const current = tagMap.get(key);
      if (current) {
        current.chunkIds.add(chunk.id);
        if (!current.tag.source && tag.source) current.tag.source = tag.source;
      } else {
        tagMap.set(key, { tag, documentLevel: false, chunkIds: new Set([chunk.id]) });
      }
    }
  }

  const tagEntries = Array.from(tagMap.entries());

  const nodes: DocumentGraphNode[] = [
    { id: "document", label: evidence.documentTitle, detail: `Document · ${evidence.version}`, type: "document", x: 50, y: 50 },
    ...evidence.chunks.map((chunk, index) => ({
      id: chunkNodeId(chunk.id),
      label: chunkGraphTitle(chunk.content, `Chunk #${chunk.chunkIndex}`),
      detail: chunk.sourceLabel,
      technicalId: chunk.id,
      type: "chunk" as const,
      contentType: chunk.type,
      ...radialPosition(index, evidence.chunks.length, 28)
    })),
    ...tagEntries.map(([key, entry], index) => {
      const source = tagSourceLabel(entry.tag);
      const prefix = entry.documentLevel ? "Document tag" : "Tag";
      const relatedDetail = `${prefix} · ${entry.chunkIds.size} chunks`;
      return {
        id: graphTagNodeId(key),
        label: entry.tag.text,
        detail: source ? `${relatedDetail} · ${source}` : relatedDetail,
        type: "tag" as const,
        ...radialPosition(index, tagEntries.length, 43, -Math.PI / 2 + Math.PI / Math.max(1, tagEntries.length))
      };
    })
  ];

  const edgeKeys = new Set<string>();
  const edges: Array<readonly [string, string]> = [];

  function addEdge(source: string, target: string) {
    const key = `${source}->${target}`;
    if (edgeKeys.has(key)) return;
    edgeKeys.add(key);
    edges.push([source, target] as const);
  }

  evidence.chunks.forEach((chunk) => addEdge("document", chunkNodeId(chunk.id)));
  tagEntries.forEach(([key, entry]) => {
    if (entry.documentLevel) addEdge("document", graphTagNodeId(key));
  });
  evidence.chunks.forEach((chunk) => {
    chunkGraphTags(chunk).forEach((tag) => addEdge(chunkNodeId(chunk.id), graphTagNodeId(graphTagKey(tag))));
  });

  return { nodes, edges };
}
