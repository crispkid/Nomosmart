
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






