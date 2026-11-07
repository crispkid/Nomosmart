import type { ApprovalTaskDetail } from "@/lib/api";

export type ReviewStepState = "complete" | "current" | "pending" | "rejected" | "cancelled";

/** Project only the request's own version/records; never the latest document. */
export function reviewWorkflow(detail: Pick<ApprovalTaskDetail, "task" | "request" | "version" | "review_records">) {
  const { task, request, version, review_records: records } = detail;
  const sameVersion = request.document_version_id === version.id && task.document_version_id === version.id;
  const cancelled = request.status === "cancelled" || task.status === "cancelled";
  function stage(name: string): ReviewStepState {
    const record = [...records].filter((item) => item.review_stage === name
      && (!request.submitted_at || Date.parse(item.created_at) >= Date.parse(request.submitted_at)))
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
    const status = record?.status ?? (task.review_stage === name ? task.status : undefined);
    if (status === "approved") return "complete";
    if (status === "rejected") return "rejected";
    if (cancelled) return "cancelled";
    if (name === "manager_review" && ["pending_owner_review", "approved", "published"].includes(request.status)) return "complete";
    if (name === "owner_review" && ["approved", "published"].includes(request.status)) return "complete";
    if (name === "owner_review" && request.status === "pending_owner_review") return "current";
    if (task.review_stage === name && status === "pending" && request.status === `pending_${name}`) return "current";
    return "pending";
  }
  const publish: ReviewStepState = request.published_at || request.status === "published"
    ? "complete" : sameVersion && ["publishing", "production_indexing", "graph_syncing"].includes(version.status)
      ? "current" : cancelled ? "cancelled" : "pending";
  return { manager: stage("manager_review"), owner: stage("owner_review"), publish };
}

export function versionPipelineState(status?: string) {
  const states = {
    pending_manager_review: "pending_manager_review", pending_owner_review: "pending_owner_review",
    approved: "publish_ready", publishing: "publishing", production_indexing: "production_indexing",
    graph_syncing: "graph_syncing", active: "published_active", review_rejected: "review_rejected",
  } as const;
  return status && Object.hasOwn(states, status) ? states[status as keyof typeof states] : null;
}

export type ExtractionOutcome = "complete" | "failed" | "running" | "waiting" | "unknown";

const automaticSteps = new Set(["upload_received", "parse_document", "ocr_extract", "generate_markdown",
  "split_paragraphs", "chunk_knowledge", "auto_tag", "build_embeddings", "build_staging_index",
  "build_graph_preview", "prepare_submission"]);
const afterExtraction = new Set(["submission_ready", "pending_manager_review", "pending_owner_review",
  "approved", "publish_ready", "publishing", "production_indexing", "graph_syncing", "active",
  "published_active", "review_rejected", "inactive"]);

/** Read-only presentation for this version, never permission to activate it. */
export function extractionOutcome(input: {
  versionStatus?: string;
  pipelineStatus?: string;
  currentStep?: string | null;
  steps?: ReadonlyArray<{ name: string; status: string }>;
}): ExtractionOutcome {
  const steps = input.steps?.filter((step) => automaticSteps.has(step.name));
  if (steps?.some((step) => step.status === "failed")) return "failed";
  if (steps?.some((step) => step.status === "running")) return "running";
  if (steps?.length && [...automaticSteps].every((name) => steps.some((step) => step.name === name
    && (step.status === "completed" || name === "ocr_extract" && step.status === "skipped")))) return "complete";
  if (afterExtraction.has(input.versionStatus ?? "") || afterExtraction.has(input.pipelineStatus ?? "")) return "complete";
  if (input.pipelineStatus === "failed" || input.versionStatus === "failed") {
    // A later publication failure is not evidence that automatic extraction failed.
    return input.currentStep && automaticSteps.has(input.currentStep) ? "failed" : "unknown";
  }
  if (["running", "processing"].includes(input.pipelineStatus ?? "") && automaticSteps.has(input.currentStep ?? "")) return "running";
  if (["queued", "waiting_action", "ready_for_extraction", "draft"].includes(input.versionStatus ?? "")
    || ["queued", "waiting_action"].includes(input.pipelineStatus ?? "")) return "waiting";
  return "unknown";
}

export function pipelineIsExecuting(status: string): boolean {
  return ["running", "processing", "publishing", "production_indexing", "graph_syncing"].includes(status);
}
