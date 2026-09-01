import type { TranslationKey } from "@/lib/i18n";

export type ResolvedSourceMapping = {
  sourceAnchor: string;
  sourceAnchors?: string[];
  markdownStart: number;
  markdownEnd: number;
  anchorStart: number;
  anchorEnd: number;
};

export type MarkdownMappedChunk = {
  id: string;
  sourceMappings: ResolvedSourceMapping[];
};

export type SourceSelectionGroup = {
  id: string;
  sourceAnchors: string[];
  sourceMappings: ResolvedSourceMapping[];
};

export type MarkdownSelectionRange = {
  start: number;
  end: number;
};

export type MarkdownSourceSegment = {
  id: string;
  text: string;
  start: number;
  end: number;
  chunkIds: string[];
  sourceAnchors: string[];
};

export function markdownArtifactReasonKey(reasonCode: string | null | undefined): TranslationKey {
  if (reasonCode === "markdown_artifact_pending") return "markdownArtifactPending";
  if (reasonCode === "markdown_artifact_step_failed") return "markdownArtifactFailed";
  if (reasonCode === "markdown_artifact_version_mismatch") return "markdownArtifactVersionMismatch";
  if (reasonCode === "markdown_artifact_invalid") return "markdownArtifactInvalid";
  return "markdownArtifactMissing";
}

function integer(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function orderedAnchors(mapping: Record<string, unknown>, sourceAnchor: string): string[] {
  const declaredAnchors = Array.isArray(mapping.source_anchors)
    ? mapping.source_anchors.filter((value): value is string => typeof value === "string" && value.length > 0)
    : [];
  const candidates = declaredAnchors.length > 0
    ? declaredAnchors
    : Array.isArray(mapping.node_ids)
      ? mapping.node_ids
      : [];
  const values = [sourceAnchor, ...candidates]
    .filter((value): value is string => typeof value === "string" && value.length > 0);
  return [...new Set(values)];
}

function mappingAnchors(mapping: ResolvedSourceMapping) {
  return mapping.sourceAnchors?.length ? mapping.sourceAnchors : [mapping.sourceAnchor];
}

export function resolvedSourceMappings(sourceMapping: unknown[]): ResolvedSourceMapping[] {
  return sourceMapping.flatMap((value) => {
    if (!value || typeof value !== "object") return [];
    const mapping = value as Record<string, unknown>;
    if (mapping.mapping_status !== "resolved" || mapping.offset_unit !== "unicode_code_point") return [];
    const sourceAnchor = mapping.source_anchor;
    const markdownStart = integer(mapping.markdown_start_offset);
    const markdownEnd = integer(mapping.markdown_end_offset);
    const anchorStart = integer(mapping.anchor_start_offset);
    const anchorEnd = integer(mapping.anchor_end_offset);
    if (typeof sourceAnchor !== "string" || !sourceAnchor || markdownStart === null || markdownEnd === null || anchorStart === null || anchorEnd === null) return [];
    if (markdownEnd <= markdownStart || anchorEnd <= anchorStart) return [];
    const sourceAnchors = orderedAnchors(mapping, sourceAnchor);
    return [{
      sourceAnchor,
      ...(sourceAnchors.length > 1 ? { sourceAnchors } : {}),
      markdownStart,
      markdownEnd,
      anchorStart,
      anchorEnd,
    }];
  });
}

export function codePointLength(value: string) {
  return Array.from(value).length;
}

export function buildMarkdownSourceSegments(source: string, chunks: MarkdownMappedChunk[]): MarkdownSourceSegment[] {
  const codePoints = Array.from(source);
  const ranges = chunks.flatMap((chunk) => chunk.sourceMappings.map((mapping) => ({ ...mapping, chunkId: chunk.id })))
    .filter((mapping) => mapping.markdownStart < mapping.markdownEnd && mapping.markdownEnd <= codePoints.length);
  const boundaries = new Set<number>([0, codePoints.length]);
  ranges.forEach((mapping) => {
    boundaries.add(mapping.markdownStart);
    boundaries.add(mapping.markdownEnd);
  });
  const ordered = [...boundaries].sort((left, right) => left - right);
  const segments: MarkdownSourceSegment[] = [];
  for (let index = 0; index < ordered.length - 1; index += 1) {
    const start = ordered[index];
    const end = ordered[index + 1];
    if (end <= start) continue;
    const overlaps = ranges.filter((mapping) => mapping.markdownStart < end && mapping.markdownEnd > start);
    segments.push({
      id: `markdown-range-${start}-${end}`,
      text: codePoints.slice(start, end).join(""),
      start,
      end,
      chunkIds: [...new Set(overlaps.map((mapping) => mapping.chunkId))],
      sourceAnchors: [...new Set(overlaps.flatMap((mapping) => mappingAnchors(mapping)))]
    });
  }
  return segments;
}

export function firstMarkdownRangeForChunk(chunk: MarkdownMappedChunk | undefined) {
  return chunk?.sourceMappings[0] ?? null;
}

export function sourceAnchorsForChunks(chunks: MarkdownMappedChunk[], selectedIds: string[]) {
  const selected = new Set(selectedIds);
  return new Set(chunks.filter((chunk) => selected.has(chunk.id)).flatMap((chunk) => chunk.sourceMappings.flatMap(mappingAnchors)));
}

export function sourceSelectionGroupsForChunks(chunks: MarkdownMappedChunk[], selectedIds: string[]): SourceSelectionGroup[] {
  const selected = new Set(selectedIds);
  return chunks
    .filter((chunk) => selected.has(chunk.id))
    .map((chunk) => ({
      id: chunk.id,
      sourceAnchors: [...new Set(chunk.sourceMappings.flatMap(mappingAnchors))],
      sourceMappings: chunk.sourceMappings,
    }))
    .filter((group) => group.sourceAnchors.length > 0 || group.sourceMappings.length > 0);
}

export function markdownSelectionRanges(group: SourceSelectionGroup): MarkdownSelectionRange[] {
  const ordered = group.sourceMappings
    .map((mapping) => ({ start: mapping.markdownStart, end: mapping.markdownEnd }))
    .filter((range) => range.end > range.start)
    .sort((left, right) => left.start - right.start || left.end - right.end);
  const merged: MarkdownSelectionRange[] = [];
  for (const range of ordered) {
    const previous = merged[merged.length - 1];
    if (previous && range.start <= previous.end) {
      previous.end = Math.max(previous.end, range.end);
    } else {
      merged.push({ ...range });
    }
  }
  return merged;
}

export function sourceSelectionScrollBehavior(): ScrollBehavior {
  if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return "auto";
  return "smooth";
}

export function chunkIdsForResolvedSourceAnchor(chunks: MarkdownMappedChunk[], sourceAnchor: string) {
  return chunks
    .filter((chunk) => chunk.sourceMappings.some((mapping) => mappingAnchors(mapping).includes(sourceAnchor)))
    .map((chunk) => chunk.id);
}
