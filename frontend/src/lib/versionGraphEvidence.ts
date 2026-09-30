import type { ProjectGraphResponse } from "@/lib/api";
import type { DocumentGraphChunk, DocumentGraphTag, GraphContentType } from "@/lib/documentGraph";

/** No KnowledgeDetail tag fallback: only relationships returned by the graph API. */
export function versionGraphEvidence(graph: ProjectGraphResponse, versionId: string, sourceLabel: string) {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  function tags(source: string, relation: string): DocumentGraphTag[] {
    return graph.edges.filter((edge) => edge.source === source && edge.type === relation).flatMap((edge) => {
      const tag = nodes.get(edge.target);
      if (tag?.type !== "Tag") return [];
      return [{ id: String(tag.metadata.technical_id ?? tag.id.replace(/^tag:/u, "")), text: tag.label,
        source: typeof edge.metadata?.source === "string" ? edge.metadata.source : null }];
    });
  }
  const chunkIds = new Set(graph.edges.filter((edge) => edge.source === versionId && edge.type === "VERSION_HAS_CHUNK").map((edge) => edge.target));
  const chunks: DocumentGraphChunk[] = graph.nodes.filter((node) => node.type === "Chunk" && chunkIds.has(node.id)).map((node) => {
    const metadata = node.metadata;
    const contentType = String(metadata.content_type ?? "text");
    return { id: node.id, chunkIndex: Number(metadata.chunk_index ?? 0), sourceLabel,
      content: typeof metadata.content === "string" ? metadata.content : "",
      displayMarkdown: typeof metadata.display_markdown === "string" ? metadata.display_markdown : null,
      markdownContent: typeof metadata.markdown_content === "string" ? metadata.markdown_content : null,
      type: (["image", "table", "chart"].includes(contentType) ? contentType : "text") as GraphContentType,
      tags: [], tagDetails: tags(node.id, "CHUNK_HAS_TAG") };
  });
  return { chunks, documentTags: tags(versionId, "VERSION_HAS_TAG") };
}
