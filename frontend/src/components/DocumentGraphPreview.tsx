"use client";

import { GraphExplorer, type GraphExplorerEdge, type GraphExplorerNode } from "@/components/GraphExplorer";
import { chunkGraphTitle, type DocumentGraphChunk, type DocumentGraphTag } from "@/lib/documentGraph";
import { useI18n } from "@/lib/i18nClient";

type DocumentGraphPreviewProps = {
  documentTags?: DocumentGraphTag[];
  documentTitle?: string;
  graphChunks?: DocumentGraphChunk[];
  version?: string;
};

function chunkNodeId(chunkId: string) {
  return `chunk-${chunkId.toLowerCase().replaceAll(/[^a-z0-9-]/g, "-")}`;
}

function tagKey(tag: DocumentGraphTag | string) {
  if (typeof tag !== "string" && tag.id.trim()) return `id:${tag.id.trim()}`;
  const text = typeof tag === "string" ? tag : tag.text;
  return `text:${text.trim().toLowerCase()}`;
}

function tagNodeId(key: string) {
  return `tag-${key.toLowerCase().replaceAll(/[^a-z0-9-]/g, "-")}`;
}

function chunkTags(chunk: DocumentGraphChunk): DocumentGraphTag[] {
  if (chunk.tagDetails?.length) return chunk.tagDetails.filter((tag) => tag.text.trim());
  return chunk.tags.filter((tag) => tag.trim()).map((tag) => ({ id: "", text: tag }));
}

const DOCUMENT_CENTER = { x: 530, y: 372 };

function arcAngle(index: number, count: number, start = -152, end = -28) {
  if (count <= 1) return -90;
  return start + ((end - start) * index) / Math.max(1, count - 1);
}

function polarPoint(center: { x: number; y: number }, radius: number, angle: number) {
  const radians = (angle * Math.PI) / 180;
  return {
    x: center.x + Math.cos(radians) * radius,
    y: center.y + Math.sin(radians) * radius
  };
}

function boundedPoint(point: { x: number; y: number }) {
  return {
    x: Math.max(74, Math.min(1006, point.x)),
    y: Math.max(70, Math.min(570, point.y))
  };
}

export function DocumentGraphPreview({
  documentTags = [],
  documentTitle,
  graphChunks = [],
  version = "v1.0"
}: DocumentGraphPreviewProps = {}) {
  const { format, t } = useI18n();
  const resolvedDocumentTitle = documentTitle ?? t("graphLegendDocument");
  const nodes: GraphExplorerNode[] = [{
    id: "document",
    kind: "document",
    meta: [
      { label: t("graphExplorerChunkCount"), value: String(graphChunks.length) },
      { label: t("graphExplorerTagCount"), value: String(documentTags.length) }
    ],
    semanticLayer: 2,
    subtitle: version,
    title: resolvedDocumentTitle,
    x: DOCUMENT_CENTER.x,
    y: DOCUMENT_CENTER.y
  }];
  const edges: GraphExplorerEdge[] = [];
  const tagMap = new Map<string, { chunkIds: Set<string>; documentLevel: boolean; tag: DocumentGraphTag; points: { angle: number; x: number; y: number }[] }>();

  if (graphChunks.length) {
    const point = boundedPoint(polarPoint(DOCUMENT_CENTER, 230, -90));
    nodes.push({
      groupCount: graphChunks.length,
      hintUntilZoom: 1.5,
      id: "chunk-density-hint",
      kind: "group",
      maxZoom: 1.49,
      revealAtZoom: 1.5,
      semanticLayer: 3,
      subtitle: format("graphChunkGroupDetail", { count: graphChunks.length }),
      title: format("graphChunkGroupLabel", { count: graphChunks.length, end: graphChunks.length, start: 1 }),
      x: point.x,
      y: point.y
    });
    edges.push({ id: "document-chunk-density-hint", label: t("graphRelationChunked"), relation: "contains", showLabel: false, source: "document", target: "chunk-density-hint" });
  }

  graphChunks.forEach((chunk, index) => {
    const id = chunkNodeId(chunk.id);
    const angle = arcAngle(index, graphChunks.length);
    const point = boundedPoint(polarPoint(DOCUMENT_CENTER, 250, angle));
    nodes.push({
      chunkContent: chunk.content,
      chunkDisplayMarkdown: chunk.displayMarkdown,
      chunkIndex: chunk.chunkIndex,
      chunkMarkdownContent: chunk.markdownContent,
      contentType: chunk.type,
      id,
      kind: "chunk",
      meta: [
        { label: t("graphDetailSource"), value: chunk.sourceLabel },
        { label: t("graphExplorerContentType"), value: t(chunk.type === "image" ? "graphContentImage" : chunk.type === "table" ? "graphContentTable" : chunk.type === "chart" ? "graphContentChart" : "graphContentText") }
      ],
      semanticLayer: 3,
      subtitle: chunk.sourceLabel,
      technicalId: chunk.id,
      title: chunkGraphTitle(chunk.content, format("graphExplorerChunkNumber", { number: chunk.chunkIndex })),
      x: point.x,
      y: point.y
    });
    edges.push({ id: `document-${id}`, label: t("graphRelationChunked"), relation: "contains", source: "document", target: id });
    chunkTags(chunk).forEach((tag) => {
      const key = tagKey(tag);
      const current = tagMap.get(key) ?? { chunkIds: new Set<string>(), documentLevel: false, tag, points: [] };
      current.chunkIds.add(chunk.id);
      current.points.push({ angle, ...point });
      if (!current.tag.source && tag.source) current.tag.source = tag.source;
      tagMap.set(key, current);
    });
  });

  documentTags.forEach((tag, index) => {
    if (!tag.text.trim()) return;
    const key = tagKey(tag);
    const angle = arcAngle(index, Math.max(1, documentTags.length), -132, -48);
    const point = boundedPoint(polarPoint(DOCUMENT_CENTER, 318, angle));
    const current = tagMap.get(key) ?? { chunkIds: new Set<string>(), documentLevel: false, tag, points: [] };
    current.documentLevel = true;
    current.points.push({ angle, ...point });
    tagMap.set(key, current);
  });

  if (tagMap.size) {
    const point = boundedPoint(polarPoint(DOCUMENT_CENTER, 306, -36));
    nodes.push({
      groupCount: tagMap.size,
      hintUntilZoom: 2,
      id: "tag-density-hint",
      kind: "tag",
      maxZoom: 1.99,
      semanticLayer: 4,
      subtitle: t("graphTagGroupDetail"),
      title: format("graphTagGroupLabel", { count: tagMap.size }),
      x: point.x,
      y: point.y
    });
    edges.push({ id: "document-tag-density-hint", label: t("graphRelationTaggedAs"), relation: "tagged_as", showLabel: false, source: "document", target: "tag-density-hint" });
  }

  Array.from(tagMap.entries()).forEach(([key, entry], index) => {
    const id = tagNodeId(key);
    const averageAngle = entry.points.length
      ? entry.points.reduce((sum, point) => sum + point.angle, 0) / entry.points.length
      : arcAngle(index, tagMap.size, -142, -38);
    const point = boundedPoint(polarPoint(DOCUMENT_CENTER, 352, averageAngle));
    nodes.push({
      groupCount: Math.max(entry.chunkIds.size, entry.documentLevel ? 1 : 0),
      id,
      kind: "tag",
      meta: [
        { label: t("graphExplorerChunkCount"), value: String(entry.chunkIds.size) },
        { label: t("graphDetailType"), value: entry.tag.source ?? "-" }
      ],
      semanticLayer: 4,
      subtitle: entry.documentLevel ? t("graphExplorerDocumentTag") : t("graphLegendTag"),
      technicalId: entry.tag.id || undefined,
      title: entry.tag.text,
      x: point.x,
      y: point.y
    });
    if (entry.documentLevel) edges.push({ id: `document-${id}`, label: t("graphRelationTaggedAs"), relation: "tagged_as", source: "document", target: id });
    entry.chunkIds.forEach((chunkId) => {
      const source = chunkNodeId(chunkId);
      edges.push({ id: `${source}-${id}`, label: t("graphRelationTaggedAs"), relation: "tagged_as", source, target: id });
    });
  });

  return (
    <GraphExplorer
      edges={edges}
      emptyMessage={t("graphExplorerEmpty")}
      nodes={nodes}
      scopeLabel={`${resolvedDocumentTitle} · ${version}`}
      statusLabel={format("graphExplorerDocumentStatus", { chunks: graphChunks.length, tags: tagMap.size })}
      title={t("graphExplorerTitle")}
    />
  );
}
