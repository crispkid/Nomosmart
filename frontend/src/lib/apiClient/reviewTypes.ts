// Approval, knowledge detail, document layout and reference types (split from lib/api.ts, OPT424-038).
import type { DocumentSummary, DocumentVersionSummary, PipelineRunDetail } from "./documentTypes";
import type { ProjectChatCitation } from "./servingTypes";

export type ApprovalTaskResponse = {
  id: string;
  approval_request_id: string;
  project_id: string;
  project_name: string | null;
  document_id: string;
  document_title: string | null;
  document_version_id: string;
  version_label: string | null;
  submitter_id: string;
  submitter_given_name: string | null;
  submitter_family_name: string | null;
  submitter_name: string | null;
  submitter_email: string | null;
  priority: string;
  source_type: string | null;
  assignee_user_id: string | null;
  original_manager_user_id?: string | null;
  review_stage: string;
  status: string;
  lock_version: number;
  submitted_at: string;
  completed_at: string | null;
  created_at: string;
};

export type ApprovalRequestResponse = {
  id: string;
  project_id: string;
  project_name: string | null;
  document_id: string;
  document_title: string | null;
  document_version_id: string;
  version_label: string | null;
  submitter_id: string;
  submitter_given_name: string | null;
  submitter_family_name: string | null;
  submitter_name: string | null;
  submitter_email: string | null;
  owner_user_id: string | null;
  evidence_revision: string | null;
  priority: string;
  source_type: string | null;
  status: string;
  current_task_id: string | null;
  submitted_at: string;
  approved_at: string | null;
  published_at: string | null;
  cancelled_at: string | null;
  created_at: string;
};

export type ApprovalPendingPublishResponse = {
  approval_request_id: string | null;
  approval_task_id: string | null;
  project_id: string;
  project_name: string | null;
  document_id: string;
  document_title: string | null;
  document_version_id: string;
  version_label: string | null;
  version_status: string;
  lock_version: number;
  submitter_id: string | null;
  submitter_given_name: string | null;
  submitter_family_name: string | null;
  submitter_name: string | null;
  submitter_email: string | null;
  approved_at: string | null;
};

export type ReviewRecordResponse = {
  id: string;
  review_stage: string;
  reviewer_id: string;
  delegated_from_user_id: string | null;
  status: string;
  comment: string | null;
  created_at: string;
};

export type ApprovalChunkEvidence = {
  id: string;
  chunk_index: number;
  title: string | null;
  content: string;
  display_markdown: string | null;
  markdown_content: string | null;
  content_type: string;
  source_mapping: unknown[];
  token_count: number | null;
  confidence_score: number | null;
  lineage_id: string;
  parent_chunk_id: string | null;
  revision: number;
  change_type: string;
  tags: string[];
  tag_details: KnowledgeTagResponse[];
};

export type KnowledgeTagResponse = {
  tag_id: string;
  tag_text: string;
  source: string;
  confidence_score: number | null;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
};

export type ApprovalChatEvidence = {
  id: string;
  conversation_id: string;
  conversation_title: string | null;
  scope_mode: string | null;
  document_version_id: string | null;
  selected_document_version_ids: string[];
  question: string;
  answer: string | null;
  reference_docs: ProjectChatCitation[];
  evaluation: string;
  revision_suggestion: string | null;
  created_by: string;
  asked_at: string;
  answered_at: string | null;
};

export type ApprovalTaskDetail = {
  task: ApprovalTaskResponse;
  request: ApprovalRequestResponse;
  document: DocumentSummary;
  version: DocumentVersionSummary;
  latest_version_id: string;
  evidence_stale: boolean;
  read_only: boolean;
  read_only_reason: string | null;
  evidence_revision: string | null;
  evidence_generated_at: string | null;
  evidence_verifiable: boolean;
  evidence_manifest: Record<string, unknown> | null;
  original_file: OriginalFileViewerMetadata | null;
  document_layout: DocumentLayoutArtifact | null;
  source_text: string | null;
  markdown_text: string | null;
  markdown_artifact_status: "available" | "processing" | "missing" | "failed" | "invalid";
  markdown_artifact_reason_code: string | null;
  source_mapping_available: boolean;
  markdown_available_count: number;
  missing_markdown_count: number;
  document_tags: KnowledgeTagResponse[];
  review_records: ReviewRecordResponse[];
  chunks: ApprovalChunkEvidence[];
  chat_records: ApprovalChatEvidence[];
};

export type KnowledgeDetailResponse = {
  staging_retention?: { expires_at: string; ttl_days: number; cleanup_status: string; expired: boolean } | null;
  chat_access?: { mode: "staging" | "published" | "history_only" | "unavailable"; document_version_id: string; query_enabled: boolean; reason_code: string | null } | null;
  document: DocumentSummary;
  version: DocumentVersionSummary;
  pipeline: PipelineRunDetail | null;
  original_file: OriginalFileViewerMetadata | null;
  document_layout: DocumentLayoutArtifact | null;
  source_text: string | null;
  markdown_text: string | null;
  markdown_artifact_status: "available" | "processing" | "missing" | "failed" | "invalid";
  markdown_artifact_reason_code: string | null;
  source_mapping_available: boolean;
  markdown_available_count: number;
  missing_markdown_count: number;
  manual_edit_enabled: boolean;
  content_edit_mode?: "readonly" | "overwrite_candidate" | "create_revision";
  content_edit_reason?: string | null;
  content_update?: import("../documentContentApi").ContentUpdateStatus | null;
  manual_edit_reason: string | null;
  tag_edit_reason?: string | null;
  active_chunk_count: number;
  chunk_artifact_status: "ready" | "queued" | "running" | "failed" | "chunks_required";
  chunk_artifact_error_code?: string | null;
  chunk_artifact_retry_allowed?: boolean | null;
  next_stage_allowed: boolean;
  next_stage_block_reason: string | null;
  document_tags: KnowledgeTagResponse[];
  chunks: ApprovalChunkEvidence[];
};

export type SubmissionEvidenceActor = {
  user_id: string;
  given_name: string | null;
  family_name: string | null;
  display_name: string;
  email: string | null;
  department: string | null;
  title: string | null;
};

export type SubmissionEvidenceResponse = {
  detail: KnowledgeDetailResponse;
  evidence_revision: string;
  lock_version: number;
  generated_at: string;
  next_stage_allowed: boolean;
  block_reasons: string[];
  can_submit_review: boolean;
  creator: SubmissionEvidenceActor | null;
  manager: SubmissionEvidenceActor | null;
  owners: SubmissionEvidenceActor[];
  models: Record<string, { id: string; name: string; type: string; provider: string; config_version: number }>;
  content_type_counts: Record<string, number>;
  chunk_count: number;
  tag_count: number;
  average_confidence: number | null;
  graph: { status?: string; source?: string; node_count?: number; edge_count?: number; chunk_count?: number };
  chat_records: ApprovalChatEvidence[];
  validation_runs: Array<Record<string, unknown>>;
};

export type DocumentLayoutArtifact = {
  status: "available" | "partial" | "missing" | "failed";
  reason_code: string | null;
  source: string | null;
  layout_version?: string | null;
  pagination?: Record<string, unknown>;
  warnings?: Array<Record<string, unknown>>;
  pages: DocumentLayoutPage[];
};

export type DocumentLayoutPage = {
  page_number: number;
  width: number | null;
  height: number | null;
  blocks: DocumentLayoutBlock[];
};

export type DocumentLayoutSourceFragment = {
  fragment_id: string;
  kind: "text" | "table_header" | "table_cell" | "list_item" | "code" | "image";
  ordinal_path: number[];
  start_offset: number;
  end_offset: number;
  offset_unit: "unicode_code_point";
  repeated_context: boolean;
  text_start_offset?: number | null;
  text_end_offset?: number | null;
};

export type DocumentLayoutBlock = {
  id: string;
  type: "heading" | "paragraph" | "list" | "table" | "image" | "caption" | "code" | "blockquote" | "horizontal_rule" | "unknown";
  source_anchor: string | null;
  text: string | null;
  inline_markdown?: string | null;
  level: number | null;
  items: string[];
  list_ordered?: boolean | null;
  list_start?: number | null;
  list_items?: DocumentLayoutListItem[];
  table_header?: string[];
  table_header_markdown?: string[];
  rows: string[][];
  rows_markdown?: string[][];
  caption: string | null;
  caption_markdown?: string | null;
  image_source?: string | null;
  code_language?: string | null;
  confidence: number | null;
  bbox: { x: number | null; y: number | null; width: number | null; height: number | null } | null;
  continuation_of?: string | null;
  continuation_index?: number | null;
  continuation_count?: number | null;
  source_start_offset?: number | null;
  source_end_offset?: number | null;
  continuation_text_start?: number | null;
  continuation_text_end?: number | null;
  source_fragments?: DocumentLayoutSourceFragment[];
};

export type DocumentLayoutListItem = {
  text: string;
  inline_markdown?: string | null;
  value?: number | null;
  children?: DocumentLayoutListItem[];
  child_lists?: Array<{
    ordered: boolean;
    start: number;
    items: DocumentLayoutListItem[];
  }>;
  continuation?: boolean;
};

export type OriginalFileViewerMetadata = {
  original_file_name: string | null;
  extension: string | null;
  mime_type: string | null;
  file_size: number | null;
  viewer_type: "download_only" | "markdown" | "unsupported";
  preview_status: "available" | "pending" | "unavailable" | "failed";
  preview_error_code: string | null;
  original_url: string | null;
  preview_url: string | null;
  download_url: string | null;
  markdown_source_mode: "rendered_original_raw_markdown" | "pipeline_markdown";
};

export type ApprovalSummary = {
  pending_total: number;
  pending_manager_review: number;
  pending_owner_review: number;
  my_submissions: number;
};

export type PublishResult = {
  document_version_id: string;
  status: string;
  active_manifest_id: string;
  publication_generation: number;
  opensearch_index: string;
  graph_sync_job_id: string;
};

export type SwitchActiveVersionPayload = {
  lock_version: number;
  impact_confirmed: boolean;
  audit_reason: string;
};

export type LifecycleImpactResponse = {
  document_id: string;
  requested_status: string;
  impacted_reference_count: number;
  impacted_active_version_count: number;
  requires_confirmation: boolean;
};

export type DocumentReferenceResponse = {
  id: string;
  target_project_id: string;
  target_document_id: string;
  source_project_id: string;
  source_document_id: string;
  source_version_id: string;
  source_project_name_snapshot: string;
  source_document_name_snapshot: string;
  reference_mode: string;
  status: string;
  created_by: string | null;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ReferenceSourceVersionResponse = {
  id: string;
  version_label: string;
  status: string;
  is_active: boolean;
  created_at: string;
};

export type ReferenceExistingTargetResponse = {
  target_document_id: string;
  target_title: string;
  source_version_label: string;
};

export type ReferenceSourceDocumentResponse = {
  id: string;
  title: string;
  owner: string | null;
  versions: ReferenceSourceVersionResponse[];
  duplicate: ReferenceExistingTargetResponse | null;
};

export type ReferenceSourceProjectResponse = {
  id: string;
  name: string;
  status: string;
  documents: ReferenceSourceDocumentResponse[];
};

export type DocumentReferenceImportResponse = {
  results: Array<{
    status: "created" | "skipped" | "failed";
    document: DocumentSummary | null;
    reference: DocumentReferenceResponse | null;
    error_code: string | null;
    message: string | null;
  }>;
};
