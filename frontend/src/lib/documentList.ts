import type { CreatedKnowledgeDocument as Document } from "../components/KnowledgeSourceModals";

export type DocumentList = { live: Document[]; created: Document[] };

const extractionVersions = new Set(["draft", "ready_for_extraction", "queued", "processing"]);
const terminalVersions = new Set(["submission_ready", "failed"]);
const terminalExecutions = new Set(["completed", "failed", "cancelled", "recovery_required"]);
const postExtractionStatuses = new Set(["submission_ready", "completed", "pending_manager_review", "pending_owner_review",
  "approved", "publish_ready", "publishing", "production_indexing", "graph_syncing", "published_active", "review_rejected"]);

function samePipeline(a: Document, b: Document): boolean {
  return Boolean(a.id === b.id && a.latestVersionId && a.latestVersionId === b.latestVersionId
    && a.pipeline.id && a.pipeline.id === b.pipeline.id);
}

/** Compare server revisions, never display dates or increasing percentages. */
function olderPipeline(a: Document, b: Document): boolean {
  const left = a.pipeline.execution;
  const right = b.pipeline.execution;
  return Boolean(left && right && (left.attempt < right.attempt
    || (left.attempt === right.attempt && left.progress_revision < right.progress_revision)));
}

/** Caller must establish same document/version/run and reject stale revisions first. */
function mergeTimes(incoming: Document["pipeline"], previous: Document["pipeline"]) {
  const sameAttempt = incoming.execution?.attempt === previous.execution?.attempt;
  const sameCompletion = incoming.status === previous.status
    || (postExtractionStatuses.has(incoming.status) && postExtractionStatuses.has(previous.status));
  return {
    startedAt: incoming.startedAt === undefined ? previous.startedAt : incoming.startedAt,
    // An absent end may fill a compatible old payload, never a retry/new state.
    completedAt: incoming.completedAt === undefined && sameAttempt && sameCompletion
      && (incoming.startedAt === undefined || incoming.startedAt === previous.startedAt)
      ? previous.completedAt : incoming.completedAt,
  };
}

/** A server summary owns governance; compatible detail only fills missing fields. */
export function reconcileDocument(server: Document, previous?: Document): Document {
  if (!previous) return server;
  if (server.lockVersion !== undefined && previous.lockVersion !== undefined
    && server.lockVersion < previous.lockVersion) return previous;
  const version = server.versions.find((item) => item.id === server.latestVersionId);
  const oldVersion = previous.versions.find((item) => item.id === server.latestVersionId);
  if (server.latestVersionId === previous.latestVersionId
    && version?.lockVersion !== undefined && oldVersion?.lockVersion !== undefined
    && version.lockVersion < oldVersion.lockVersion) return previous;
  if (!samePipeline(server, previous)) return server;
  if (server.versionStatus === previous.versionStatus && olderPipeline(server, previous)) {
    return { ...server, pipeline: previous.pipeline };
  }
  // Only carry step detail when it describes the SAME observed state. A newer
  // summary can legitimately have lower progress (e.g. a retry).
  const equivalent = server.pipeline.status === previous.pipeline.status
    && server.pipeline.progress === previous.pipeline.progress
    && server.pipeline.currentStep === previous.pipeline.currentStep;
  const times = olderPipeline(server, previous)
    ? { startedAt: previous.pipeline.startedAt, completedAt: previous.pipeline.completedAt }
    : mergeTimes(server.pipeline, previous.pipeline);
  if (server.versionStatus !== previous.versionStatus || !equivalent
    || olderPipeline(previous, server)) return { ...server, pipeline: { ...server.pipeline, ...times } };
  const cleanupResolved = server.pipeline.execution && terminalExecutions.has(server.pipeline.execution.phase);
  return { ...server, pipeline: {
    ...server.pipeline,
    ...times,
    steps: server.pipeline.steps ?? previous.pipeline.steps,
    execution: server.pipeline.execution === undefined ? previous.pipeline.execution : server.pipeline.execution,
    observationInterrupted: server.pipeline.observationInterrupted ?? (cleanupResolved ? false : previous.pipeline.observationInterrupted),
    cleanupObservationStopped: server.pipeline.cleanupObservationStopped ?? (cleanupResolved ? false : previous.pipeline.cleanupObservationStopped),
  } };
}

export function uniqueDocuments(documents: Document[]): Document[] {
  const byId = new Map<string, Document>();
  for (const document of documents) {
    // First occurrence is the caller's latest receipt; retain its ordering.
    if (!byId.has(document.id)) byId.set(document.id, document);
  }
  return [...byId.values()];
}

export function documentListItems(state: DocumentList): Document[] {
  const liveById = new Map(state.live.map((document) => [document.id, document]));
  return uniqueDocuments([
    ...state.created.map((document) => liveById.has(document.id)
      ? reconcileDocument(liveById.get(document.id)!, document) : document),
    ...state.live,
  ]);
}

/** Atomically hand confirmed IDs to the server list, retaining unacknowledged IDs. */
export function refreshDocumentList(state: DocumentList, documents: Document[]): DocumentList {
  const previous = new Map(documentListItems(state).map((document) => [document.id, document]));
  const live = uniqueDocuments(documents).map((document) => reconcileDocument(document, previous.get(document.id)));
  const ids = new Set(live.map((document) => document.id));
  return { live, created: uniqueDocuments(state.created).filter((document) => !ids.has(document.id)) };
}

/** A start receipt may introduce a new run, but not overwrite a superseding version/run. */
export function receiveExtractionReceipt(state: DocumentList, expected: Document, receipt: Document): DocumentList {
  if (!receipt.isLive || receipt.id !== expected.id || receipt.latestVersionId !== expected.latestVersionId
    || !receipt.pipeline.id) return state;
  const update = (current: Document): Document => {
    if (current.id !== expected.id || current.latestVersionId !== expected.latestVersionId
      || current.pipeline.id !== expected.pipeline.id || current.versionStatus !== expected.versionStatus
      || current.documentStatus !== expected.documentStatus) return current;
    const currentVersion = current.versions.find((item) => item.id === current.latestVersionId);
    const receivedVersion = receipt.versions.find((item) => item.id === receipt.latestVersionId);
    if (currentVersion?.lockVersion !== undefined && receivedVersion?.lockVersion !== undefined
      && currentVersion.lockVersion > receivedVersion.lockVersion) return current;
    const merged = reconcileDocument(receipt, current);
    if (merged !== current) return merged;
    // A concurrent rename can advance only the document lock. Keep its metadata
    // while accepting the start receipt for this unchanged version/previous run.
    return { ...current, sourceState: receipt.sourceState, versionStatus: receipt.versionStatus,
      extractionSuccessful: receipt.extractionSuccessful, extractionOutcome: receipt.extractionOutcome,
      versions: current.versions.map((version) => version.id === receipt.latestVersionId
        ? { ...version, status: receipt.versionStatus, lockVersion: receivedVersion?.lockVersion ?? version.lockVersion } : version),
      pipeline: receipt.pipeline };
  };
  return { live: state.live.map(update), created: state.created.map(update) };
}

/** Unlike upload receipts, a GET must never create a missing/deleted list item. */
export function receivePipelineDocuments(state: DocumentList, documents: Document[]): DocumentList {
  const known = new Set([...state.live, ...state.created].filter((item) => item.documentStatus !== "deleted").map((item) => item.id));
  return receiveUploadDocuments(state, documents.filter((item) => known.has(item.id)));
}

/** Upload polling may update its pipeline, never revert a server-selected version. */
export function receiveUploadDocuments(state: DocumentList, documents: Document[]): DocumentList {
  const incoming = new Map(uniqueDocuments(documents).map((document) => [document.id, document]));
  const update = (current: Document): Document => {
    const next = incoming.get(current.id);
    if (!next || current.documentStatus === "deleted" || !samePipeline(current, next) || olderPipeline(next, current)) return current;
    // Governance/review changes take priority over a poll started during extraction.
    const confirmedRetry = current.versionStatus === "failed"
      && current.pipeline.execution && next.pipeline.execution
      && next.pipeline.execution.attempt > current.pipeline.execution.attempt;
    if (!extractionVersions.has(current.versionStatus) && !confirmedRetry) {
      if (!terminalVersions.has(current.versionStatus) || current.versionStatus !== next.versionStatus
        || current.pipeline.status !== next.pipeline.status) return current;
      // Extraction completion and execution cleanup are distinct. A late detail
      // must not replace the completed percentage/steps or governance snapshot.
      const previousExecution = current.pipeline.execution;
      const execution = next.pipeline.execution ?? previousExecution;
      if (previousExecution && terminalExecutions.has(previousExecution.phase)
        && execution && !terminalExecutions.has(execution.phase)) return current;
      return { ...current, pipeline: { ...current.pipeline, execution,
        ...mergeTimes(next.pipeline, current.pipeline),
        observationInterrupted: next.pipeline.observationInterrupted ?? current.pipeline.observationInterrupted,
        cleanupObservationStopped: next.pipeline.cleanupObservationStopped ?? current.pipeline.cleanupObservationStopped,
      } };
    }
    // A document rename can advance its lock while this same pipeline keeps
    // running. Keep all current governance fields; compare pipeline evidence
    // independently rather than discarding valid progress with an old title.
    return { ...current,
      versionStatus: next.versionStatus,
      chunks: next.versionStatus === "submission_ready" ? null : current.chunks,
      chunkCountRunId: undefined,
      sourceState: next.sourceState,
      extractionSuccessful: next.extractionSuccessful,
      extractionOutcome: next.extractionOutcome,
      versions: current.versions.map((version) => version.id === current.latestVersionId
        ? { ...version, status: next.versionStatus } : version),
      pipeline: reconcileDocument({ ...current, pipeline: next.pipeline }, current).pipeline,
    };
  };
  const knownIds = new Set([...state.live, ...state.created].map((document) => document.id));
  return {
    live: state.live.map(update),
    created: uniqueDocuments([
      ...documents.filter((document) => !knownIds.has(document.id)),
      ...state.created.map(update),
    ]),
  };
}
