"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { GraphExplorer, type GraphExplorerEdge, type GraphExplorerNode } from "@/components/GraphExplorer";
import { getProjectGraph, getProjectGraphNeighbors, type ProjectGraphResponse } from "@/lib/api";
import { chunkGraphTitle } from "@/lib/documentGraph";
import { useI18n } from "@/lib/i18nClient";

type SourceNodeKind = "chunk" | "document" | "project" | "tag";
type SourceNode = {
  id: string;
  kind: SourceNodeKind;
  label: string;
  metadata: Record<string, unknown>;
  rawType: string;
  technicalId?: string;
};

function isTechnicalId(value: string) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function sourceKind(type: string): SourceNodeKind {
  const lower = type.toLowerCase();
  if (lower.includes("project")) return "project";
  if (lower.includes("document")) {
    if (lower.includes("chunk")) return "chunk";
    return "document";
  }
  if (lower.includes("chunk")) return "chunk";
  return "tag";
}

const GRAPH_CENTER = { x: 540, y: 320 };

function polarPoint(radius: number, angle: number, verticalScale = 0.72) {
  const radians = (angle * Math.PI) / 180;
  return {
    x: GRAPH_CENTER.x + Math.cos(radians) * radius,
    y: GRAPH_CENTER.y + Math.sin(radians) * radius * verticalScale
  };
}

function radialAngle(index: number, count: number) {
  if (count <= 1) return 0;
  return -90 + (360 * index) / count;
}

function sectorAngle(anchorAngle: number, index: number, count: number, spread: number) {
  if (count <= 1) return anchorAngle;
  return anchorAngle - spread / 2 + (spread * index) / Math.max(1, count - 1);
}

function metadataString(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function metadataNumber(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function metadataContent(metadata: Record<string, unknown>) {
  const value = metadata.content;
  return typeof value === "string" ? value : undefined;
}

function metadataMarkdown(metadata: Record<string, unknown>, key: "display_markdown" | "markdown_content") {
  const value = metadata[key];
  return typeof value === "string" ? value : undefined;
}

function metadataContentType(metadata: Record<string, unknown>): GraphExplorerNode["contentType"] {
  const value = metadataString(metadata, "content_type") ?? metadataString(metadata, "type");
  if (value === "image" || value === "table" || value === "chart" || value === "text") return value;
  return "text";
}

function sourceRelationshipLabel(metadata: Record<string, unknown>, labels: ProjectGraphLabels) {
  const raw = [
    metadataString(metadata, "source_type"),
    metadataString(metadata, "source"),
    metadataString(metadata, "import_source"),
    metadataString(metadata, "source_protocol"),
    metadataString(metadata, "protocol"),
    metadataString(metadata, "reference_mode")
  ].filter(Boolean).join(" ").toLowerCase();
  if (raw.includes("reference") || raw.includes("referenced") || raw.includes("project_reference")) return labels.referenceProject;
  if (raw.includes("http") || raw.includes("api")) return labels.httpApi;
  if (raw.includes("sftp")) return labels.sftp;
  if (raw.includes("ftps")) return labels.ftps;
  if (raw.includes("ftp")) return labels.ftp;
  if (raw.includes("ssh")) return labels.ssh;
  if (raw.includes("s3") || raw.includes("rustfs")) return labels.s3;
  return labels.upload;
}

function addToSet(map: Map<string, Set<string>>, key: string, value: string) {
  const current = map.get(key) ?? new Set<string>();
  current.add(value);
  map.set(key, current);
}

function compareChunks(a: SourceNode, b: SourceNode) {
  const aIndex = metadataNumber(a.metadata, "chunk_index") ?? metadataNumber(a.metadata, "index");
  const bIndex = metadataNumber(b.metadata, "chunk_index") ?? metadataNumber(b.metadata, "index");
  if (aIndex !== null && bIndex !== null && aIndex !== bIndex) return aIndex - bIndex;
  if (aIndex !== null) return -1;
  if (bIndex !== null) return 1;
  return a.label.localeCompare(b.label);
}

type ProjectGraphLabels = {
  chunkCount: string;
  chunkNumber: (number: number) => string;
  chunkGroupDetail: (count: number) => string;
  chunkGroupLabel: (start: number, end: number, count: number) => string;
  chunks: string;
  contains: string;
  document: string;
  ftp: string;
  ftps: string;
  httpApi: string;
  project: string;
  referenceProject: string;
  s3: string;
  sftp: string;
  ssh: string;
  tagCount: string;
  tagGroupDetail: string;
  tagGroupLabel: (count: number) => string;
  taggedAs: string;
  tags: string;
  type: string;
  upload: string;
  version: string;
  versionStatus: string;
};

function buildProjectExplorerGraph(graph: ProjectGraphResponse, labels: ProjectGraphLabels) {
  const sourceNodes: SourceNode[] = graph.nodes.filter((node) => !node.type.toLowerCase().includes("version")).map((node) => {
    const kind = sourceKind(node.type);
    const label = node.label && !isTechnicalId(node.label)
      ? node.label
      : kind === "project" ? labels.project : kind === "document" ? labels.document : kind === "chunk" ? labels.chunks : labels.tags;
    return {
      id: node.id,
      kind,
      label,
      metadata: node.metadata,
      rawType: node.type,
      technicalId: metadataString(node.metadata, "technical_id") ?? node.id
    };
  });
  const sourceById = new Map(sourceNodes.map((node) => [node.id, node]));
  const projectNode = sourceNodes.find((node) => node.kind === "project") ?? {
    id: `project-${graph.project_id}`,
    kind: "project" as const,
    label: labels.project,
    metadata: {},
    rawType: "Project",
    technicalId: graph.project_id ?? undefined
  };
  const documentNodes = sourceNodes.filter((node) => node.kind === "document");
  const nodes: GraphExplorerNode[] = [{
    id: projectNode.id,
    kind: "project",
    meta: [
      { label: labels.document, value: String(documentNodes.length) },
      { label: labels.chunkCount, value: String(sourceNodes.filter((node) => node.kind === "chunk").length) },
      { label: labels.tagCount, value: String(sourceNodes.filter((node) => node.kind === "tag").length) }
    ],
    semanticLayer: 1,
    subtitle: projectNode.rawType,
    technicalId: projectNode.technicalId,
    title: projectNode.label,
    x: GRAPH_CENTER.x,
    y: GRAPH_CENTER.y
  }];
  const edges: GraphExplorerEdge[] = [];
  const documentChunkIds = new Map<string, Set<string>>();
  const documentTagIds = new Map<string, Set<string>>();
  const chunkTagIds = new Map<string, Set<string>>();
  const projectDocumentSources = new Map<string, string>();
  const versionIds = new Set(graph.nodes.filter((node) => node.type.toLowerCase().includes("version")).map((node) => node.id));
  const versionToDocument = new Map<string, string>();

  graph.edges.forEach((edge) => {
    if (versionIds.has(edge.target) && sourceById.get(edge.source)?.kind === "document") {
      versionToDocument.set(edge.target, edge.source);
    } else if (versionIds.has(edge.source) && sourceById.get(edge.target)?.kind === "document") {
      versionToDocument.set(edge.source, edge.target);
    }
  });

  graph.edges.forEach((edge) => {
    const sourceVersionDocument = versionToDocument.get(edge.source);
    const targetVersionDocument = versionToDocument.get(edge.target);
    if (sourceVersionDocument) {
      const targetNode = sourceById.get(edge.target);
      if (targetNode?.kind === "chunk") addToSet(documentChunkIds, sourceVersionDocument, targetNode.id);
      if (targetNode?.kind === "tag") addToSet(documentTagIds, sourceVersionDocument, targetNode.id);
    }
    if (targetVersionDocument) {
      const sourceNode = sourceById.get(edge.source);
      if (sourceNode?.kind === "chunk") addToSet(documentChunkIds, targetVersionDocument, sourceNode.id);
      if (sourceNode?.kind === "tag") addToSet(documentTagIds, targetVersionDocument, sourceNode.id);
    }
    const source = sourceById.get(edge.source);
    const target = sourceById.get(edge.target);
    if (!source || !target) return;
    const project = source.kind === "project" ? source : target.kind === "project" ? target : null;
    const document = source.kind === "document" ? source : target.kind === "document" ? target : null;
    const chunk = source.kind === "chunk" ? source : target.kind === "chunk" ? target : null;
    const tag = source.kind === "tag" ? source : target.kind === "tag" ? target : null;
    if (project && document) projectDocumentSources.set(document.id, edge.type);
    if (document && chunk) addToSet(documentChunkIds, document.id, chunk.id);
    if (document && tag) addToSet(documentTagIds, document.id, tag.id);
    if (chunk && tag) addToSet(chunkTagIds, chunk.id, tag.id);
  });


  documentNodes.forEach((node, documentIndex) => {
    const documentAngle = radialAngle(documentIndex, documentNodes.length);
    const versionSummary = metadataString(node.metadata, "version_label");
    const versionStatus = metadataString(node.metadata, "version_status");
    const related = {
      chunks: documentChunkIds.get(node.id) ?? new Set<string>(),
      tags: documentTagIds.get(node.id) ?? new Set<string>()
    };
    const relatedChunks = Array.from(related.chunks)
      .map((id) => sourceById.get(id))
      .filter((chunk): chunk is SourceNode => Boolean(chunk))
      .sort(compareChunks);
    const chunkLevelTagIds = new Set<string>();
    const relatedTags = Array.from(related.tags)
      .map((id) => sourceById.get(id))
      .filter((tag): tag is SourceNode => Boolean(tag))
      .sort((a, b) => a.label.localeCompare(b.label));
    nodes.push({
      id: node.id,
      kind: "document",
      meta: [
        { label: labels.chunkCount, value: String(related.chunks.size) },
        { label: labels.tagCount, value: String(related.tags.size) },
        ...(versionSummary ? [{ label: labels.version, value: versionSummary }] : []),
        ...(versionStatus ? [{ label: labels.versionStatus, value: versionStatus }] : [])
      ],
      semanticLayer: 2,
      subtitle: labels.document,
      technicalId: node.technicalId,
      title: node.label,
      ...polarPoint(250, documentAngle, 0.64)
    });
    edges.push({
      id: `${projectNode.id}-${node.id}`,
      label: sourceRelationshipLabel({ ...node.metadata, source_type: projectDocumentSources.get(node.id) ?? metadataString(node.metadata, "source_type") ?? "" }, labels),
      relation: "source",
      source: projectNode.id,
      target: node.id
    });
    relatedChunks.forEach((chunk, chunkIndex) => {
      const chunkAngle = sectorAngle(documentAngle, chunkIndex, Math.max(relatedChunks.length, 1), Math.min(170, Math.max(84, relatedChunks.length * 8)));
      const chunkNodeId = `${node.id}-chunk-${chunk.id}`;
      const canonicalIndex = metadataNumber(chunk.metadata, "chunk_index");
      const content = metadataContent(chunk.metadata);
      const displayMarkdown = metadataMarkdown(chunk.metadata, "display_markdown");
      const markdownContent = metadataMarkdown(chunk.metadata, "markdown_content");
      nodes.push({
        ...(content !== undefined ? { chunkContent: content } : {}),
        ...(displayMarkdown !== undefined ? { chunkDisplayMarkdown: displayMarkdown } : {}),
        ...(canonicalIndex !== null ? { chunkIndex: canonicalIndex } : {}),
        ...(markdownContent !== undefined ? { chunkMarkdownContent: markdownContent } : {}),
        contentType: metadataContentType(chunk.metadata),
        id: chunkNodeId,
        kind: "chunk",
        meta: [
          { label: labels.type, value: chunk.rawType },
          { label: labels.document, value: node.label }
        ],
        semanticLayer: 3,
        subtitle: metadataString(chunk.metadata, "source_anchor") ?? labels.chunks,
        technicalId: chunk.technicalId,
        title: chunkGraphTitle(content, canonicalIndex === null ? labels.chunks : labels.chunkNumber(canonicalIndex)),
        ...polarPoint(410, chunkAngle, 0.58)
      });
      edges.push({ id: `${node.id}-${chunkNodeId}`, label: labels.contains, relation: "contains", showLabel: false, source: node.id, target: chunkNodeId });
      chunkTagIds.get(chunk.id)?.forEach((tagId) => {
        const tagNodeId = `${node.id}-tag-${tagId}`;
        edges.push({ id: `${chunkNodeId}-${tagNodeId}`, label: labels.taggedAs, relation: "tagged_as", showLabel: false, source: chunkNodeId, target: tagNodeId });
        chunkLevelTagIds.add(tagId);
      });
    });

    const docTagSet = new Set(relatedTags.map(t => t.id));

    relatedTags.forEach((tag, tagIndex) => {
      const tagAngle = sectorAngle(documentAngle, tagIndex, Math.max(relatedTags.length, 1), Math.min(210, Math.max(96, relatedTags.length * 9)));
      const tagNodeId = `${node.id}-tag-${tag.id}`;
      nodes.push({
        id: tagNodeId,
        kind: "tag",
        meta: [
          { label: labels.type, value: tag.rawType },
          { label: labels.document, value: node.label }
        ],
        semanticLayer: 4,
        subtitle: labels.tags,
        technicalId: tag.technicalId,
        title: tag.label,
        ...polarPoint(520, tagAngle, 0.5)
      });
      if (documentTagIds.get(node.id)?.has(tag.id)) {
        edges.push({ id: `${node.id}-${tagNodeId}`, label: labels.taggedAs, relation: "tagged_as", showLabel: false, source: node.id, target: tagNodeId });
      }
    });

    Array.from(chunkLevelTagIds).forEach((tagId, tagIndex) => {
      if (docTagSet.has(tagId)) return; // Already rendered as a document-level tag
      const tag = sourceById.get(tagId);
      if (!tag) return;
      const tagAngle = sectorAngle(documentAngle, tagIndex + relatedTags.length, Math.max(chunkLevelTagIds.size + relatedTags.length, 1), Math.min(230, Math.max(112, (chunkLevelTagIds.size + relatedTags.length) * 9)));

      const tagNodeId = `${node.id}-tag-${tag.id}`;
      nodes.push({
        id: tagNodeId,
        kind: "tag",
        meta: [
          { label: labels.type, value: tag.rawType },
          { label: labels.document, value: node.label }
        ],
        semanticLayer: 4,
        subtitle: labels.tags,
        technicalId: tag.technicalId,
        title: tag.label,
        ...polarPoint(540, tagAngle, 0.48)
      });
      // Do not add an edge to the document. The edges to chunks are already added above.
    });
  });

  return { edges, nodes };
}

function mergeProjectGraphs(current: ProjectGraphResponse, incoming: ProjectGraphResponse): ProjectGraphResponse {
  const nodes = new Map(current.nodes.map((node) => [node.id, node]));
  incoming.nodes.forEach((node) => nodes.set(node.id, node));
  const edges = new Map(current.edges.map((edge) => [edge.id, edge]));
  incoming.edges.forEach((edge) => edges.set(edge.id, edge));
  return {
    project_id: current.project_id,
    nodes: Array.from(nodes.values()),
    edges: Array.from(edges.values()),
    truncated: current.truncated || incoming.truncated,
    node_limit: Math.max(current.node_limit, incoming.node_limit)
  };
}

export function ProjectGraphPreview() {
  const params = useParams<{ id?: string }>();
  const { apiFetch, authReady } = useAuth();
  const { format, t } = useI18n();
  const [liveGraph, setLiveGraph] = useState<ProjectGraphResponse | null>(null);
  const [graphStatus, setGraphStatus] = useState<"empty" | "error" | "not-ready" | "forbidden" | "live" | "loading">("loading");
  const [expandingNodeId, setExpandingNodeId] = useState<string | null>(null);

  useEffect(() => {
    const projectId = params?.id;
    if (!authReady || !projectId) return;
    let cancelled = false;
    getProjectGraph(apiFetch, projectId, 120).then((graph) => {
      if (cancelled) return;
      setLiveGraph(graph);
      setGraphStatus(graph.nodes.length ? "live" : "empty");
    }).catch((error: Error & { status?: number; code?: string }) => {
      if (cancelled) return;
      setLiveGraph(null);
      setGraphStatus(error.status === 403 ? "forbidden" : ["graph_projection_not_ready", "graph_identity_conflict"].includes(error.code ?? "") ? "not-ready" : "error");
    });
    return () => { cancelled = true; };
  }, [apiFetch, authReady, params?.id]);

  function expandNeighborGraph(nodeId: string) {
    const projectId = params?.id;
    if (!authReady || !projectId || expandingNodeId === nodeId || graphStatus !== "live") return;
    setExpandingNodeId(nodeId);
    getProjectGraphNeighbors(apiFetch, projectId, nodeId, 80).then((neighborGraph) => {
      setLiveGraph((current) => current ? mergeProjectGraphs(current, neighborGraph) : neighborGraph);
    }).catch((error: { code?: string }) => {
      if (["graph_projection_not_ready", "graph_identity_conflict"].includes(error.code ?? "")) {
        setLiveGraph(null);
        setGraphStatus("not-ready");
      }
    }).finally(() => setExpandingNodeId((current) => current === nodeId ? null : current));
  }

  const graph = useMemo(() => liveGraph ? buildProjectExplorerGraph(liveGraph, {
    chunkCount: t("graphExplorerChunkCount"),
    chunkNumber: (number) => format("graphExplorerChunkNumber", { number }),
    chunkGroupDetail: (count) => format("graphChunkGroupDetail", { count }),
    chunkGroupLabel: (start, end, count) => format("graphChunkGroupLabel", { count, end, start }),
    chunks: t("graphLegendChunk"),
    contains: t("graphRelationChunked"),
    document: t("graphLegendDocument"),
    ftp: t("graphRelationSourceFtp"),
    ftps: t("graphRelationSourceFtps"),
    httpApi: t("graphRelationSourceHttpApi"),
    project: t("graphLegendProject"),
    referenceProject: t("graphRelationSourceReferenceProject"),
    s3: t("graphRelationSourceS3"),
    sftp: t("graphRelationSourceSftp"),
    ssh: t("graphRelationSourceSsh"),
    tagCount: t("graphExplorerTagCount"),
    tagGroupDetail: t("graphTagGroupDetail"),
    tagGroupLabel: (count) => format("graphTagGroupLabel", { count }),
    taggedAs: t("graphRelationTaggedAs"),
    tags: t("graphLegendTag"),
    type: t("graphDetailType"),
    upload: t("graphRelationSourceUpload"),
    version: t("graphExplorerVersion"),
    versionStatus: t("graphExplorerVersionStatus")
  }) : { edges: [], nodes: [] }, [format, liveGraph, t]);

  const statusLabel = graphStatus === "live" && liveGraph?.truncated
    ? format("graphProjectTruncatedStatus", { limit: liveGraph.node_limit, nodes: graph.nodes.length })
    : graphStatus === "live"
      ? format("graphProjectLiveStatus", { edges: graph.edges.length, nodes: graph.nodes.length })
      : graphStatus === "empty"
        ? t("graphProjectEmptyStatus")
        : graphStatus === "forbidden"
          ? t("graphProjectForbiddenStatus")
          : graphStatus === "loading"
            ? t("graphProjectLoadingStatus")
            : graphStatus === "not-ready" ? t("graphProjectionNotReady") : t("graphProjectUnavailableStatus");

  return (
    <GraphExplorer
      edges={graph.edges}
      emptyMessage={statusLabel}
      nodes={graph.nodes}
      onNodeSelect={expandNeighborGraph}
      scopeLabel={t("graphExplorerProjectScope")}
      statusLabel={statusLabel}
      title={t("graphExplorerTitle")}
    />
  );
}
