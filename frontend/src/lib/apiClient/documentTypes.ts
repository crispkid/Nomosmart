// Pipeline, document, upload and data source types (split from lib/api.ts, OPT424-038).
import type { ProjectCapabilities } from "./projectTypes";

export type PipelineExecution = {
  phase: string;
  attempt: number;
  progress_revision: number;
  updated_at: string;
  heartbeat_at: string | null;
  completed_units: number;
  total_units: number | null;
  unit: "pages" | "steps" | null;
  safe_error_code: string | null;
  poll_interval_seconds: number;
  background_poll_interval_seconds: number;
};

export type PipelineSummary = {
  id: string | null;
  status: string;
  progress_percent: number;
  current_step_name: string | null;
  error_message: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  execution?: PipelineExecution | null;
};

export type ChunkingIssue = {
  code: "chunk_atomic_unit_too_large" | "chunk_model_capacity_unavailable" | "chunk_source_unresolved";
  unit_type: string; node_id: string | null; table_id: string | null;
  row_start: number | null; row_end: number | null; start_offset: number; end_offset: number;
  offset_unit: "unicode_code_point"; canonical_sha256: string | null;
  input_tokens: number | null; input_token_limit: number | null; tokenizer_version: string | null;
  capacity_source: string; can_edit_content: boolean; action_required: string;
};

export type PipelineStepSummary = {
  id: string;
  step_name: string;
  status: string;
  progress_percent: number;
  progress_message: string | null;
  retry_count: number;
  output_artifact_ref: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  input_mode?: "page_images" | "native_pdf" | null;
  page_output_token_limit?: number | null;
  request_output_token_limit?: number | null;
  page_map_status?: "known" | "unknown" | null;
  source_precision?: "page" | "document" | null;
  document_output_token_limit?: number | null;
  confirmed_output_tokens?: number | null;
  remaining_output_tokens?: number | null;
  chunking_issue?: ChunkingIssue | null;
  retry_allowed?: boolean | null;
  ocr_call_state?: "idle" | "in_flight" | "unconfirmed" | null;
  processed_pages?: number | null;
  total_pages?: number | null;
  error_code?: string | null;
};

export type PipelineRunDetail = PipelineSummary & {
  project_id: string;
  document_id: string | null;
  document_version_id: string | null;
  run_type: string;
  started_at: string | null;
  steps: PipelineStepSummary[];
};

export type DocumentVersionSummary = {
  active_chunk_count?: number | null;
  created_by?: string | null;
  created_by_name?: string | null;
  id: string;
  version_label: string;
  status: string;
  original_file_name: string | null;
  canonical_extension: string | null;
  mime_type: string | null;
  file_size: number | null;
  storage_bucket: string | null;
  storage_key: string | null;
  ocr_model_id: string | null;
  ocr_config_version: number | null;
  lock_version: number;
  created_at: string;
  updated_at: string;
};

export type DocumentSummary = {
  created_by_name?: string | null;
  id: string;
  project_id: string;
  document_code: string;
  title: string;
  source_type: string;
  status: string;
  created_by: string | null;
  lock_version: number;
  created_at: string;
  updated_at: string;
  latest_version: DocumentVersionSummary | null;
  versions?: DocumentVersionSummary[];
  latest_pipeline: PipelineSummary | null;
  service_source?: DocumentServiceSourceSummary | null;
  reference_source?: DocumentReferenceSourceSummary | null;
  capabilities: ProjectCapabilities;
};

export type DocumentServiceSourceSummary = {
  data_source_id: string;
  service_type: string;
  location: string;
  schedule_mode: string;
  cron_expression: string | null;
  timezone: string | null;
};

export type DocumentReferenceSourceSummary = {
  reference_id: string | null;
  source_project_id: string;
  source_document_id: string;
  source_version_id: string;
  project_name: string;
  document_name: string;
  snapshot_version: string;
  latest_active_version: string | null;
  has_access: boolean;
  status: string;
  detected_at: string | null;
  pending_event_count: number;
};

export type DocumentUploadResult = {
  index: number;
  filename: string;
  status: "success" | "failed";
  document: DocumentSummary | null;
  started_extraction: boolean;
  error_code: string | null;
  message: string | null;
};

export type DocumentUploadResponse = {
  request_id: string;
  success_count: number;
  failed_count: number;
  results: DocumentUploadResult[];
};

export type DocumentUpdateResponse = {
  document: DocumentSummary;
  latest_pipeline: PipelineSummary | null;
  no_change: boolean;
  message: string | null;
};

export type DataSourceConnectionPayload = {
  service_type: "FTP" | "FTPS" | "SFTP" | "S3" | "HTTP_API";
  name: string;
  host: string;
  port: number;
  username: string;
  credential?: string | null;
  credential_secret_ref?: string | null;
  bucket?: string | null;
  region?: string | null;
  remote_path: string;
  file_name: string;
  schedule_mode: "once" | "cron";
  cron_expression?: string | null;
  timezone: string;
  verify_tls?: boolean;
  verify_host_key?: boolean;
  url?: string | null;
  headers?: Record<string, string>;
  auth_mode?: "none" | "bearer" | "api_key_header";
  api_key_header_name?: string | null;
  timeout_seconds?: number;
  max_bytes?: number | null;
};

export type DataSourceConnectionTestResponse = {
  status: "success" | "configuration_valid" | "unavailable" | "failed";
  detail_code: string;
  message: string;
  credential_configured: boolean;
  fingerprint: string | null;
  latency_ms: number | null;
  tested_at: string | null;
};

export type DataSourceResponse = {
  id: string;
  project_id: string;
  service_type: string;
  name: string;
  connection_metadata: Record<string, unknown>;
  source_identity: Record<string, unknown>;
  schedule_mode: string;
  cron_expression: string | null;
  timezone: string;
  enabled: boolean;
  last_sync_status: string | null;
  last_synced_at: string | null;
  next_run_at: string | null;
  lock_version: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  credential_configured: boolean;
  last_test_status: string | null;
  last_tested_at: string | null;
  last_test_fingerprint: string | null;
  last_test_latency_ms: number | null;
  last_test_detail_code: string | null;
  last_test_actor_id: string | null;
};

export type DataSyncRunResponse = {
  id: string;
  data_connection_id: string;
  document_id: string;
  trigger_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  content_fingerprint: string | null;
  remote_metadata: Record<string, unknown>;
  document_version_id: string | null;
  error_code: string | null;
  error_summary: string | null;
  retry_count: number;
  created_at: string;
};

export type DataSourceCreateResponse = {
  data_source: DataSourceResponse;
  document: DocumentSummary;
  sync_run: DataSyncRunResponse;
};
