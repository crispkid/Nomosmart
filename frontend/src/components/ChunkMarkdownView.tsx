"use client";

import { SafeMarkdown } from "@/components/SafeMarkdown";

export type ChunkMarkdownSource = {
  content?: string | null;
  display_markdown?: string | null;
  markdown_content?: string | null;
};

export type SelectedChunkMarkdownSource = {
  kind: "display_markdown" | "markdown_content" | "content";
  source: string;
};

/**
 * Selects only complete, user-authorized display representations.
 * Retrieval text and bounded previews are intentionally not accepted here so
 * they cannot accidentally become a full Markdown renderer input.
 */
export function selectChunkMarkdownSource(chunk: ChunkMarkdownSource): SelectedChunkMarkdownSource | null {
  const candidates: SelectedChunkMarkdownSource[] = [
    { kind: "display_markdown", source: chunk.display_markdown ?? "" },
    { kind: "markdown_content", source: chunk.markdown_content ?? "" },
    { kind: "content", source: chunk.content ?? "" },
  ];
  return candidates.find(({ source }) => source.trim().length > 0) ?? null;
}

export function ChunkMarkdownView({
  chunk,
  className = "",
}: {
  chunk: ChunkMarkdownSource;
  className?: string;
}) {
  const selected = selectChunkMarkdownSource(chunk);
  if (!selected) return null;
  return (
    <SafeMarkdown
      className={["chunk-markdown-view", "markdown-semantic-content", className].filter(Boolean).join(" ")}
      source={selected.source}
    />
  );
}
