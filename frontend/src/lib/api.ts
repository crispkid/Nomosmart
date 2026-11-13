// Typed API client for the NomoSmart backend. The implementation is split by domain into lib/apiClient/* (OPT424-038);
// this module re-exports the public names so every "@/lib/api" import is unchanged.
export { can, canAnyView, apiJson } from "./apiClient/core";
export type { PermissionAction, PermissionGrant, CurrentUser, ApiError, ApiFetch } from "./apiClient/core";
export type {
  UserRoleSummary, UserSummary, RoleResponse, PermissionValue, PermissionMatrixResponse, RoleUsersResponse,
  CountedPage, SystemListOptions, DataSourceConnectionOptions, ExternalGroupResponse, ExternalGroupRoleMapping,
  RoleExternalGroupMappingResponse, IdentitySyncProviderResultResponse, IdentitySyncRunResponse,
  OperationComponentStatus, OperationRecentError, OperationsStatusResponse, AIModelResponse, AIModelListPage,
  SystemPromptVersionResponse, SystemPromptResponse
} from "./apiClient/identityTypes";
export type {
  ProjectResponse, ProjectCapabilities, ProjectListOptions, ProjectListPage, ProjectArchiveImpactResponse,
  IntegrationClientResponse, IntegrationClientCreateResponse, IntegrationClientPage, IntegrationClientPayload,
  ProjectCreatePayload, ProjectMemberResponse, ProjectMemberCandidate, ProjectMemberCandidatePage,
  ProjectMemberUpdatePayload
} from "./apiClient/projectTypes";
export type {
  PipelineExecution, PipelineSummary, ChunkingIssue, PipelineStepSummary, PipelineRunDetail,
  DocumentVersionSummary, DocumentSummary, DocumentServiceSourceSummary, DocumentReferenceSourceSummary,
  DocumentUploadResult, DocumentUploadResponse, DocumentUpdateResponse, DataSourceConnectionPayload,
  DataSourceConnectionTestResponse, DataSourceResponse, DataSyncRunResponse, DataSourceCreateResponse
} from "./apiClient/documentTypes";
export type {
  ApprovalTaskResponse, ApprovalRequestResponse, ApprovalPendingPublishResponse, ReviewRecordResponse,
  ApprovalChunkEvidence, KnowledgeTagResponse, ApprovalChatEvidence, ApprovalTaskDetail, KnowledgeDetailResponse,
  SubmissionEvidenceActor, SubmissionEvidenceResponse, DocumentLayoutArtifact, DocumentLayoutPage,
  DocumentLayoutSourceFragment, DocumentLayoutBlock, DocumentLayoutListItem, OriginalFileViewerMetadata,
  ApprovalSummary, PublishResult, SwitchActiveVersionPayload, LifecycleImpactResponse, DocumentReferenceResponse,
  ReferenceSourceVersionResponse, ReferenceExistingTargetResponse, ReferenceSourceDocumentResponse,
  ReferenceSourceProjectResponse, DocumentReferenceImportResponse
} from "./apiClient/reviewTypes";
export type {
  ProjectGraphResponse, ProjectServingStatusResponse, ProjectChatQueryResponse, ProjectChatCitation,
  ProjectChatRecordResponse, ProjectChatConversationResponse, ProjectChatConversationPage,
  ProjectChatConversationDeleteResponse, ValidationRunResponse, ReportMetricCard, ReportProjectRankingItem,
  ReportSummaryResponse, ReportFilterOptionsResponse, NotificationResponse, NotificationCountResponse,
  SystemParametersPayload, SystemParameterApiValues, SystemParameterSectionResponse,
  SystemParametersUpdatePayload, UploadConfigResponse, SessionDraftRestoreResponse, BreakGlassStatusResponse,
  AIModelPayload, AIModelUpdatePayload, SystemPromptPayload, SystemPromptVersionPayload
} from "./apiClient/servingTypes";
export {
  getCurrentUser, restoreSessionDraft, discardSessionDraft, listProjectsPage, listProjects, getProject,
  createProject, getProjectArchiveImpact, archiveProject, retryProjectArchiveCleanup, listIntegrationClients,
  listIntegrationClientsPage, getIntegrationClient, getDataSourceConnectionOptions, createIntegrationClient,
  updateIntegrationClient, replaceIntegrationClientProjectScopes, rotateIntegrationClientKey,
  activateIntegrationClient, deactivateIntegrationClient, revokeIntegrationClient, listProjectMembers,
  searchProjectMemberCandidates, replaceProjectMember, removeProjectMember, listProjectDocuments,
  uploadProjectDocuments, updateProjectDocumentFile, testDataSourceConnection, createDataSource,
  queueDataSourceSync, listDataSourceSyncRuns, startDocumentExtraction, getPipelineDetail, getKnowledgeDetail,
  createManualChunk, deleteKnowledgeChunk, addChunkTag, deleteChunkTag, autoTagChunk, addDocumentTag,
  deleteDocumentTag, autoTagDocument, getKnowledgeArtifactBlob, retryPipelineStep,
  getDocumentVersionSubmissionEvidence, submitDocumentVersionReview, getApprovalSummary
} from "./apiClient/projectRequests";
export {
  listApprovalFilterOptions, listPendingApprovalsPage, listApprovalHistoryPage, listRejectedApprovalsPage,
  listMyApprovalSubmissionsPage, listPendingApprovals, listApprovalHistory, listRejectedApprovals,
  listMyApprovalSubmissions, listPendingPublishApprovals, listPendingPublishApprovalsPage, getApprovalTask,
  approveApprovalTask, rejectApprovalTask, publishDocumentVersion, switchActiveDocumentVersion,
  getDocumentLifecycleImpact, updateDocumentLifecycle, listProjectReferenceSources,
  importProjectDocumentReferences, updateDocumentReferenceVersion, getProjectGraph, getProjectGraphNeighbors,
  getDocumentVersionGraph, getProjectServingStatus, queryProjectChat, listProjectChatConversationPage,
  getProjectChatConversation, downloadProjectChatConversationCsv, deleteProjectChatConversation,
  updateProjectChatFeedback, createProjectChatValidationRun, getProjectChatValidationRun,
  retryFailedProjectChatValidationItems, getReportFilterOptions, getReportSummary, downloadReportCsv,
  listNotificationPage, getNotificationUnreadCount, markNotificationRead, markAllNotificationsRead,
  resolveNotification
} from "./apiClient/reviewRequests";
export type {
  CursorPage, ApprovalPendingPublishPage, ApprovalTab, ApprovalListFilters, ModelUsageReportFilters,
  ReportQueryParams, NotificationPage
} from "./apiClient/reviewRequests";
export {
  listUsersPage, listRolesPage, getUser, getRole, listUsers, updateUser, updateUserStatus, listRoles, createRole,
  updateRole, deleteRole, listModelsPage, listModels, createModel, updateModel, deleteModel, setDefaultModel,
  testModel, listSystemPrompts, createSystemPrompt, addSystemPromptVersion, activateSystemPrompt,
  deactivateSystemPrompt, getPermissions, replacePermissions, getRoleUsers, replaceRoleUsers, listExternalGroups,
  listExternalGroupMappings, setRoleExternalGroupMapping, getSystemParameters, getUploadConfig,
  updateSystemParameters, getSystemStatus, getBreakGlassStatus, queueIdentitySync, listIdentitySyncRuns,
  getIdentitySyncRun, patchSystemParameters
} from "./apiClient/systemRequests";
