"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Archive, ArrowRight, ArrowUpDown, BrainCircuit, CheckCircle2, ChevronLeft, ChevronRight, FileCheck2, Files, FileText, FolderKanban, LoaderCircle, Plus, RefreshCw, Search, Settings, SlidersHorizontal, Workflow, X } from "lucide-react";
import { AppShell, ForbiddenState, Panel, StatusBadge } from "@/components/AppShell";
import { useAuth } from "@/components/AuthProvider";
import { archiveProject, createProject, getProjectArchiveImpact, listModels, listProjectsPage, retryProjectArchiveCleanup, type AIModelResponse, type ApiError, type ProjectArchiveImpactResponse, type ProjectResponse } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";

const tabs = [
  { id: "active", labelKey: "projectsTabAll" },
  { id: "archived", labelKey: "projectsTabArchived" }
] as const;

const PROJECT_PAGE_SIZE = 12;
type ProjectRoleFilter = "owner" | "editor" | "viewer";
type ProjectModelFilter = "all" | "complete" | "incomplete";
type ProjectSort = "updated_desc" | "updated_asc" | "name_asc" | "name_desc";

const modelGroupKeys = ["model_group", "modelGroup", "model_family", "modelFamily", "deployment_group", "deploymentGroup", "project_group", "projectGroup"];

function modelPairKey(model: AIModelResponse) {
  for (const key of modelGroupKeys) {
    const value = model.config[key];
    if (typeof value === "string" && value.trim()) return `group:${value.trim().toLowerCase()}`;
  }
  return `provider:${model.provider.trim().toLowerCase()}`;
}

function pairedEmbeddingModelIds(model: AIModelResponse) {
  const value = model.config.paired_embedding_model_ids;
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

export default function ProjectsPage() {
  const { locale, t, format } = useI18n();
  const { apiFetch, can } = useAuth();
  const canView = can("Menu", "KnowledgeProjects", "view");
  const canCreate = can("Menu", "KnowledgeProjects", "create");
  const canManageModels = can("Menu", "SystemManagement", "view");
  const [activeTab, setActiveTab] = useState<"active" | "archived">("active");
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [totalProjects, setTotalProjects] = useState(0);
  const [models, setModels] = useState<AIModelResponse[]>([]);
  const [modelLoadState, setModelLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [modelLoadError, setModelLoadError] = useState<ApiError | Error | null>(null);
  const [modelRefreshVersion, setModelRefreshVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [createError, setCreateError] = useState<ApiError | Error | null>(null);
  const [creating, setCreating] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<ProjectResponse | null>(null);
  const [archiveImpact, setArchiveImpact] = useState<ProjectArchiveImpactResponse | null>(null);
  const [archiveConfirmation, setArchiveConfirmation] = useState("");
  const [archiveError, setArchiveError] = useState<ApiError | Error | null>(null);
  const [loadingArchiveImpact, setLoadingArchiveImpact] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [retryingArchiveId, setRetryingArchiveId] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);
  const [roleFilters, setRoleFilters] = useState<ProjectRoleFilter[]>([]);
  const [draftRoleFilters, setDraftRoleFilters] = useState<ProjectRoleFilter[]>([]);
  const [modelFilter, setModelFilter] = useState<ProjectModelFilter>("all");
  const [draftModelFilter, setDraftModelFilter] = useState<ProjectModelFilter>("all");
  const [projectSort, setProjectSort] = useState<ProjectSort>("updated_desc");
  const [page, setPage] = useState(1);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const chatModels = useMemo(() => models.filter((model) => model.model_type.toLowerCase() === "chat"), [models]);
  const embeddingModels = useMemo(() => models.filter((model) => model.model_type.toLowerCase() === "embedding"), [models]);
  const ocrModels = useMemo(() => models.filter((model) => model.model_type.toLowerCase() === "ocr"), [models]);
  const activeChatModels = useMemo(() => chatModels.filter((model) => model.is_active && !model.deleted_at), [chatModels]);
  const activeEmbeddingModels = useMemo(() => embeddingModels.filter((model) => model.is_active && !model.deleted_at), [embeddingModels]);
  const activeOcrModels = useMemo(() => ocrModels.filter((model) => model.is_active && !model.deleted_at), [ocrModels]);
  const [llmModelId, setLlmModelId] = useState("");
  const [embeddingModelId, setEmbeddingModelId] = useState("");
  const [ocrModelId, setOcrModelId] = useState("");
  const filterControlRef = useRef<HTMLDivElement>(null);
  const filterButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(searchInput.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    if (!canView) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      void listProjectsPage(apiFetch, {
        status: activeTab,
        q: query,
        roles: roleFilters,
        modelState: modelFilter === "all" ? undefined : modelFilter,
        sort: projectSort,
        offset: (page - 1) * PROJECT_PAGE_SIZE,
        limit: PROJECT_PAGE_SIZE,
        signal: controller.signal
      }).then((result) => {
        setTotalProjects(result.total);
        const lastAvailablePage = Math.max(1, Math.ceil(result.total / PROJECT_PAGE_SIZE));
        if (page > lastAvailablePage) {
          setProjects([]);
          setPage(lastAvailablePage);
          return;
        }
        setProjects(result.items);
      }).catch((caught: ApiError | Error) => {
        if (caught.name !== "AbortError") setError(caught);
      }).finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [activeTab, apiFetch, canView, modelFilter, page, projectSort, query, refreshVersion, roleFilters]);

  useEffect(() => {
    if (!canCreate) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setModelLoadState("loading");
      setModelLoadError(null);
      void listModels(apiFetch).then((modelRows) => {
        if (!active) return;
        setModels(modelRows);
        const isEligible = (model: AIModelResponse) => model.is_active && !model.deleted_at;
        const defaultChat = modelRows.find((model) => model.model_type.toLowerCase() === "chat" && model.is_default && isEligible(model)) ?? modelRows.find((model) => model.model_type.toLowerCase() === "chat" && isEligible(model));
        const defaultEmbedding = modelRows.find((model) => model.model_type.toLowerCase() === "embedding" && model.is_default && isEligible(model)) ?? modelRows.find((model) => model.model_type.toLowerCase() === "embedding" && isEligible(model));
        const defaultOcr = modelRows.find((model) => model.model_type.toLowerCase() === "ocr" && model.is_default && isEligible(model)) ?? modelRows.find((model) => model.model_type.toLowerCase() === "ocr" && isEligible(model));
        setLlmModelId((current) => modelRows.some((model) => model.id === current && model.model_type.toLowerCase() === "chat" && isEligible(model)) ? current : defaultChat?.id || "");
        setEmbeddingModelId((current) => modelRows.some((model) => model.id === current && model.model_type.toLowerCase() === "embedding" && isEligible(model)) ? current : defaultEmbedding?.id || "");
        setOcrModelId((current) => modelRows.some((model) => model.id === current && model.model_type.toLowerCase() === "ocr" && isEligible(model)) ? current : defaultOcr?.id || "");
        setModelLoadState("ready");
      }).catch((caught: ApiError | Error) => {
        if (!active) return;
        setModelLoadError(caught);
        setModelLoadState("error");
      });
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [apiFetch, canCreate, modelRefreshVersion]);

  useEffect(() => {
    if (!filterOpen) return;
    function handlePointerDown(event: PointerEvent) {
      if (event.target instanceof Node && !filterControlRef.current?.contains(event.target)) setFilterOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setFilterOpen(false);
      window.requestAnimationFrame(() => filterButtonRef.current?.focus());
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [filterOpen]);

  const modelStateLabel = (active: boolean) => active ? t("systemEnabled") : t("systemDisabled");
  const errorMessage = (operationalError: ApiError | Error | null, fallbackKey?: "apiGenericError") => operationalErrorMessage(operationalError, t, format, fallbackKey);
  const selectedLlmModel = useMemo(() => activeChatModels.find((model) => model.id === llmModelId) ?? null, [activeChatModels, llmModelId]);
  const explicitPairedEmbeddingIds = selectedLlmModel ? pairedEmbeddingModelIds(selectedLlmModel) : [];
  const selectedLlmPairKey = selectedLlmModel ? modelPairKey(selectedLlmModel) : "";
  const pairedEmbeddingModels = selectedLlmModel
    ? explicitPairedEmbeddingIds.length
      ? activeEmbeddingModels.filter((model) => explicitPairedEmbeddingIds.includes(model.id))
      : activeEmbeddingModels.filter((model) => modelPairKey(model) === selectedLlmPairKey)
    : activeEmbeddingModels;
  const hasActivePairedEmbeddingModel = pairedEmbeddingModels.length > 0;
  const pairedDefaultEmbeddingModel = pairedEmbeddingModels.find((model) => model.is_default) ?? pairedEmbeddingModels[0];
  const effectiveEmbeddingModelId = pairedEmbeddingModels.some((model) => model.id === embeddingModelId) ? embeddingModelId : pairedDefaultEmbeddingModel?.id ?? "";
  const hasCompatibleModelPair = activeChatModels.some((chatModel) => {
    const explicitIds = pairedEmbeddingModelIds(chatModel);
    return explicitIds.length
      ? activeEmbeddingModels.some((embeddingModel) => explicitIds.includes(embeddingModel.id))
      : activeEmbeddingModels.some((embeddingModel) => modelPairKey(embeddingModel) === modelPairKey(chatModel));
  });
  const missingModelTypes = [
    !activeChatModels.length ? t("projectsModelTypeChat") : null,
    !activeOcrModels.length ? t("projectsModelTypeOcr") : null,
    !activeEmbeddingModels.length ? t("projectsModelTypeEmbedding") : null,
  ].filter((value): value is string => Boolean(value));
  const missingModelList = new Intl.ListFormat(locale === "zh" ? "zh-Hant" : "en", { style: "long", type: "conjunction" }).format(missingModelTypes);
  const modelReadinessBlocked = modelLoadState !== "ready" || missingModelTypes.length > 0 || !hasCompatibleModelPair;

  async function submitProject() {
    setCreateError(null);
    if (!name.trim()) {
      setCreateError(Object.assign(new Error("project_name_required"), { status: 422, code: "project_name_required" }) as ApiError);
      return;
    }
    if (modelReadinessBlocked || !llmModelId || !effectiveEmbeddingModelId || !ocrModelId) {
      setCreateError(Object.assign(new Error("project_model_configuration_required"), { status: 422, code: "project_model_configuration_required" }) as ApiError);
      return;
    }
    if (!selectedLlmModel || !hasActivePairedEmbeddingModel) {
      setCreateError(Object.assign(new Error("project_model_pair_required"), { status: 422, code: "project_model_pair_required" }) as ApiError);
      return;
    }
    setCreating(true);
    try {
      await createProject(apiFetch, {
        name: name.trim(),
        description: description.trim() || null,
        llm_model_id: llmModelId,
        embedding_model_id: effectiveEmbeddingModelId,
        ocr_model_id: ocrModelId
      });
      setIsCreateOpen(false);
      setName("");
      setDescription("");
      setOcrModelId("");
      setActiveTab("active");
      setPage(1);
      setRefreshVersion((version) => version + 1);
    } catch (caught) {
      setCreateError(caught as ApiError | Error);
    } finally {
      setCreating(false);
    }
  }

  async function openArchive(project: ProjectResponse) {
    if (!project.capabilities.can_archive_project) return;
    setArchiveTarget(project);
    setArchiveImpact(null);
    setArchiveConfirmation("");
    setArchiveError(null);
    setLoadingArchiveImpact(true);
    try {
      setArchiveImpact(await getProjectArchiveImpact(apiFetch, project.id));
    } catch (caught) {
      setArchiveError(caught as ApiError | Error);
    } finally {
      setLoadingArchiveImpact(false);
    }
  }

  function closeArchive() {
    if (archiving) return;
    setArchiveTarget(null);
    setArchiveImpact(null);
    setArchiveConfirmation("");
    setArchiveError(null);
  }

  async function confirmArchive() {
    if (!archiveTarget || !archiveImpact || archiveConfirmation !== archiveTarget.name) return;
    setArchiving(true);
    setArchiveError(null);
    try {
      await archiveProject(apiFetch, archiveTarget.id, { lock_version: archiveImpact.lock_version, confirmation_name: archiveConfirmation });
      setArchiveTarget(null);
      setArchiveImpact(null);
      setArchiveConfirmation("");
      setActiveTab("archived");
      setPage(1);
    } catch (caught) {
      setArchiveError(caught as ApiError | Error);
    } finally {
      setArchiving(false);
    }
  }

  async function retryArchiveCleanup(project: ProjectResponse) {
    if (!project.capabilities.can_retry_archive_cleanup) return;
    setRetryingArchiveId(project.id);
    setError(null);
    try {
      await retryProjectArchiveCleanup(apiFetch, project.id);
      setRefreshVersion((version) => version + 1);
    } catch (caught) {
      setError(caught as ApiError | Error);
    } finally {
      setRetryingArchiveId(null);
    }
  }

  function changeTab(tab: "active" | "archived") {
    setActiveTab(tab);
    setPage(1);
  }

  function openFilters() {
    setDraftRoleFilters(roleFilters);
    setDraftModelFilter(modelFilter);
    setFilterOpen(true);
  }

  function toggleDraftRole(role: ProjectRoleFilter) {
    setDraftRoleFilters((current) => current.includes(role) ? current.filter((value) => value !== role) : [...current, role]);
  }

  function applyFilters() {
    setRoleFilters(draftRoleFilters);
    setModelFilter(draftModelFilter);
    setPage(1);
    setFilterOpen(false);
    window.requestAnimationFrame(() => filterButtonRef.current?.focus());
  }

  function clearFilters() {
    setDraftRoleFilters([]);
    setDraftModelFilter("all");
    setRoleFilters([]);
    setModelFilter("all");
    setPage(1);
    setFilterOpen(false);
    window.requestAnimationFrame(() => filterButtonRef.current?.focus());
  }

  const activeFilterCount = roleFilters.length + (modelFilter === "all" ? 0 : 1);
  const totalPages = Math.max(1, Math.ceil(totalProjects / PROJECT_PAGE_SIZE));
  const resultFirst = totalProjects ? (page - 1) * PROJECT_PAGE_SIZE + 1 : 0;
  const resultLast = Math.min(page * PROJECT_PAGE_SIZE, totalProjects);
  const hasDiscoveryCriteria = Boolean(query || activeFilterCount);

  function projectAuthorityLabel(project: ProjectResponse) {
    if (project.is_owner) return t("projectsAuthorityOwner");
    if (project.capabilities.can_archive_project || project.capabilities.can_retry_archive_cleanup) return t("projectsAuthorityArchivePermission");
    if (project.current_user_project_roles.includes("editor")) return t("projectsAuthorityEditor");
    return t("projectsAuthorityViewer");
  }

  function projectModelCount(project: ProjectResponse) {
    return [project.llm_model_id, project.embedding_model_id, project.ocr_model_id].filter(Boolean).length;
  }

  function projectActivity(project: ProjectResponse) {
    const value = project.last_activity_at ?? project.archived_at;
    return value ? new Date(value).toLocaleString() : "—";
  }

  return (
    <AppShell title={t("dashboard")}>
      {!canView ? <ForbiddenState /> : <>
        <div className="tab-row">
          {tabs.map((tab) => <button className={activeTab === tab.id ? "tab active" : "tab"} key={tab.id} onClick={() => changeTab(tab.id)} type="button">{t(tab.labelKey)}</button>)}
          {activeTab === "active" ? <button className="action-button project-create-trigger" disabled={!canCreate} onClick={() => setIsCreateOpen(true)} title={!canCreate ? t("apiForbidden") : undefined} type="button">
            <Plus size={16} /> {t("projectsCreateProject")}
          </button> : null}
        </div>

        <Panel title={t("projectsListTitle")} action={<span aria-live="polite" className="project-result-summary">{format("projectsResultSummary", { first: resultFirst, last: resultLast, total: totalProjects })}</span>}>
          <section aria-label={t("projectsDiscoveryTools")} className="project-discovery-toolbar">
            <label className="project-search-field">
              <Search aria-hidden="true" size={17} />
              <input aria-label={t("projectsSearchLabel")} onChange={(event) => setSearchInput(event.target.value)} placeholder={t("projectsSearchPlaceholder")} type="search" value={searchInput} />
              {searchInput ? <button aria-label={t("projectsClearSearch")} className="project-search-clear" onClick={() => setSearchInput("")} type="button"><X size={15} /></button> : null}
            </label>
            <div className="project-discovery-actions">
              <div className="project-filter-control" ref={filterControlRef}>
                <button aria-expanded={filterOpen} className={activeFilterCount ? "project-tool-button active" : "project-tool-button"} onClick={() => filterOpen ? setFilterOpen(false) : openFilters()} ref={filterButtonRef} type="button"><SlidersHorizontal size={16} />{t("projectsFilter")}{activeFilterCount ? <span>{activeFilterCount}</span> : null}</button>
                {filterOpen ? <section aria-label={t("projectsFilter")} className="project-filter-popover">
                  <fieldset><legend>{t("projectsRoleFilter")}</legend>{(["owner", "editor", "viewer"] as ProjectRoleFilter[]).map((role) => <label key={role}><input checked={draftRoleFilters.includes(role)} onChange={() => toggleDraftRole(role)} type="checkbox" /><span>{t(`projectsRole_${role}`)}</span></label>)}</fieldset>
                  <fieldset><legend>{t("projectsModelFilter")}</legend>{(["all", "complete", "incomplete"] as ProjectModelFilter[]).map((state) => <label key={state}><input checked={draftModelFilter === state} name="project-model-filter" onChange={() => setDraftModelFilter(state)} type="radio" /><span>{t(`projectsModelFilter_${state}`)}</span></label>)}</fieldset>
                  <footer><button className="text-link" onClick={clearFilters} type="button">{t("projectsClearFilters")}</button><button className="action-button" onClick={applyFilters} type="button">{t("projectsApplyFilters")}</button></footer>
                </section> : null}
              </div>
              <label className="project-sort-control"><ArrowUpDown aria-hidden="true" size={16} /><span className="sr-only">{t("projectsSortLabel")}</span><select aria-label={t("projectsSortLabel")} onChange={(event) => { setProjectSort(event.target.value as ProjectSort); setPage(1); }} value={projectSort}><option value="updated_desc">{t("projectsSortUpdatedDesc")}</option><option value="updated_asc">{t("projectsSortUpdatedAsc")}</option><option value="name_asc">{t("projectsSortNameAsc")}</option><option value="name_desc">{t("projectsSortNameDesc")}</option></select></label>
            </div>
          </section>

          {loading ? <div className="project-list-loading" role="status"><LoaderCircle className="spin" size={20} />{t("loadingData")}</div> : null}
          {error ? <div className="error-summary" role="alert"><strong>{errorMessage(error)}</strong><button className="text-link" onClick={() => setRefreshVersion((version) => version + 1)} type="button">{t("retry")}</button></div> : null}
          {!loading && !error && projects.length === 0 ? <div className="empty-state">{hasDiscoveryCriteria ? t("projectsNoMatchingProjects") : t("projectsNoVisibleProjects")}{hasDiscoveryCriteria ? <button className="text-link" onClick={() => { setSearchInput(""); setQuery(""); clearFilters(); }} type="button">{t("projectsClearDiscovery")}</button> : null}</div> : null}
          <div className="project-grid">
            {projects.map((project) => (
              <article className={`project-card project-card-large${project.status === "archived" ? " archived" : ""}`} key={project.id}>
<header className="project-card-header"><span className="project-icon"><FolderKanban size={21} /></span><div><h3>{project.name}</h3><small>{format("projectsLastActivity", { time: projectActivity(project) })}</small></div><span className={`project-authority-badge${project.is_owner ? " owner" : (project.capabilities.can_archive_project || project.capabilities.can_retry_archive_cleanup) ? " execute" : ""}`}>{projectAuthorityLabel(project)}</span></header>
                <p className="project-card-description">{project.description || t("projectsNoDescription")}</p>
                <dl className="project-card-metrics">
                  <div><dt><Files size={16} />{t("projectsDocumentCount")}</dt><dd>{project.document_count}</dd></div>
                  <div><dt><FileCheck2 size={16} />{t("projectsPublishedVersionCount")}</dt><dd>{project.published_version_count}</dd></div>
                  <div><dt><BrainCircuit size={16} />{t("projectsModelCompleteness")}</dt><dd>{projectModelCount(project)}/3</dd></div>
                </dl>
                <footer className="project-card-footer">
                  <div className="project-card-status"><StatusBadge status={project.status} />{project.status === "archived" ? <small>{t(`projectsArchiveCleanup_${project.archive_cleanup_status || "queued"}`)}</small> : projectModelCount(project) === 3 ? <small><CheckCircle2 size={14} />{t("projectsModelsReady")}</small> : <small>{t("projectsModelsIncomplete")}</small>}</div>
                  <div className="project-card-actions">
                    {project.status === "active" && project.capabilities.can_archive_project ? <button className="project-archive-action" onClick={() => void openArchive(project)} type="button"><Archive size={15} />{t("projectsArchiveAction")}</button> : null}
                    {project.status === "active" ? <Link className="project-enter-action" href={`/project/${project.id}/import`}>{t("projectsOpenProject")}<ArrowRight size={16} /></Link> : <span className="archived-project-lock"><Archive size={15} />{t("projectsArchivedUnavailable")}</span>}
                    {project.status === "archived" && project.capabilities.can_retry_archive_cleanup && project.archive_cleanup_status === "failed" ? <button className="project-retry-action" disabled={retryingArchiveId === project.id} onClick={() => void retryArchiveCleanup(project)} type="button">{retryingArchiveId === project.id ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}{t("projectsArchiveCleanupRetry")}</button> : null}
                  </div>
                </footer>
              </article>
            ))}
          </div>
          {totalPages > 1 ? <nav aria-label={t("projectsPagination")} className="project-pagination"><span>{format("projectsPageSummary", { page, total: totalPages })}</span><div><button aria-label={t("systemPreviousPage")} className="icon-button" disabled={loading || page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} type="button"><ChevronLeft size={17} /></button><button aria-label={t("systemNextPage")} className="icon-button" disabled={loading || page >= totalPages} onClick={() => setPage((current) => Math.min(totalPages, current + 1))} type="button"><ChevronRight size={17} /></button></div></nav> : null}
        </Panel>

        {isCreateOpen ? (
          <div className="modal-backdrop" role="presentation">
            <section aria-modal="true" className="modal-panel create-project-modal" role="dialog">
              <div className="modal-header"><div><p className="eyebrow">{t("knowledgeProjectLabel")}</p><h2>{t("projectsAddProject")}</h2></div><button aria-label={t("projectsCloseCreateProjectModal")} className="icon-button" onClick={() => setIsCreateOpen(false)} type="button"><X size={18} /></button></div>
              {createError ? <div className="error-summary" role="alert"><strong>{errorMessage(createError)}</strong></div> : null}
              {modelReadinessBlocked ? <div className="project-model-readiness" id="project-model-readiness" role="alert">
                {modelLoadState === "loading" ? <LoaderCircle aria-hidden="true" className="spin" size={20} /> : <AlertTriangle aria-hidden="true" size={20} />}
                <div>
                  <strong>{t("projectsModelReadinessTitle")}</strong>
                  {modelLoadState === "loading" ? <p>{t("projectsModelReadinessLoading")}</p> : null}
                  {modelLoadState === "error" ? <><p>{t("projectsModelReadinessLoadFailed")}</p>{modelLoadError ? <small>{errorMessage(modelLoadError)}</small> : null}</> : null}
                  {modelLoadState === "ready" && missingModelTypes.length ? <p>{format("projectsModelReadinessMissing", { models: missingModelList })}</p> : null}
                  {modelLoadState === "ready" && !missingModelTypes.length && !hasCompatibleModelPair ? <p>{t("projectsModelPairRequired")}</p> : null}
                  {modelLoadState !== "loading" ? <div className="project-model-readiness-actions">
                    {modelLoadState === "error" ? <button className="text-link" onClick={() => setModelRefreshVersion((version) => version + 1)} type="button"><RefreshCw size={15} />{t("projectsModelReadinessRetry")}</button> : null}
                    {canManageModels ? <Link className="text-link" href="/system?tab=models"><Settings size={15} />{t("projectsGoToAiModels")}</Link> : <span>{t("projectsContactAdministrator")}</span>}
                  </div> : null}
                </div>
              </div> : null}
              <div className="create-project-scroll">
	                <div className="create-project-grid">
	                  <section className="create-section"><div className="create-section-title"><FileText size={18} /><h3>{t("projectsBasicInfo")}</h3></div><div className="form-grid"><label>{t("projectsName")}<input onChange={(event) => setName(event.target.value)} placeholder={t("projectsNamePlaceholder")} value={name} /></label><label className="wide">{t("systemDescription")}<textarea onChange={(event) => setDescription(event.target.value)} placeholder={t("projectsDescriptionPlaceholder")} value={description} /></label></div></section>
	                  <section className="create-section"><div className="create-section-title"><FileText size={18} /><h3>{t("projectsOcrModel")}</h3></div><div className="model-option-grid">{activeOcrModels.map((model) => <label className={model.id === ocrModelId ? "model-option selected" : "model-option"} key={model.id}><input checked={model.id === ocrModelId} name="ocr-model" onChange={() => setOcrModelId(model.id)} type="radio" /><strong>{model.name}</strong><small>{model.provider} · OCR · {modelStateLabel(model.is_active)}</small></label>)}{!activeOcrModels.length ? <p className="field-note">{t("projectsNoOcrModel")}</p> : null}</div></section>
	                  <section className="create-section"><div className="create-section-title"><BrainCircuit size={18} /><h3>{t("projectsLlmModel")}</h3></div><div className="model-option-grid">{activeChatModels.map((model) => <label className={model.id === llmModelId ? "model-option selected" : "model-option"} key={model.id}><input checked={model.id === llmModelId} name="llm-model" onChange={() => setLlmModelId(model.id)} type="radio" /><strong>{model.name}</strong><small>{model.provider} · {model.model_type} · {modelStateLabel(model.is_active)}</small></label>)}{!activeChatModels.length ? <p className="field-note">{t("projectsNoChatModel")}</p> : null}</div></section>
	                  <section className="create-section"><div className="create-section-title"><Workflow size={18} /><h3>{t("projectsEmbeddingModel")}</h3></div><p className="field-note">{selectedLlmModel ? t("projectsEmbeddingPairHelp") : t("projectsEmbeddingModelSelectLlmHelp")}</p><div className="model-option-grid">{pairedEmbeddingModels.map((model) => <label className={model.id === effectiveEmbeddingModelId ? "model-option selected" : "model-option"} key={model.id}><input checked={model.id === effectiveEmbeddingModelId} name="embedding-model" onChange={() => setEmbeddingModelId(model.id)} type="radio" /><strong>{model.name}</strong><small>{model.provider} · Embedding · {modelStateLabel(model.is_active)}</small></label>)}{!activeEmbeddingModels.length ? <p className="field-note">{t("projectsNoEmbeddingModel")}</p> : null}{activeEmbeddingModels.length && !pairedEmbeddingModels.length ? <p className="field-note">{t("projectsNoPairedEmbeddingModel")}</p> : null}</div></section>
	                </div>
              </div>
              <div className="modal-actions"><button className="action-button secondary" onClick={() => setIsCreateOpen(false)} type="button">{t("cancel")}</button><button aria-describedby={modelReadinessBlocked ? "project-model-readiness" : undefined} className="action-button" disabled={creating || modelReadinessBlocked || !selectedLlmModel || !hasActivePairedEmbeddingModel || !ocrModelId || !effectiveEmbeddingModelId} onClick={submitProject} title={modelReadinessBlocked ? t("projectsCreateDisabledModels") : undefined} type="button"><Plus size={16} /> {creating ? t("projectsCreating") : t("projectsCreateProject")}</button></div>
            </section>
          </div>
        ) : null}

        {archiveTarget ? (
          <div className="modal-backdrop" role="presentation">
            <section aria-modal="true" className="modal-panel project-archive-modal" role="dialog">
              <div className="modal-header"><div className="modal-title-with-icon"><span className="danger-icon"><AlertTriangle size={20} /></span><div><h2>{t("projectsArchiveTitle")}</h2><p>{archiveTarget.name}</p></div></div><button aria-label={t("close")} className="icon-button" disabled={archiving} onClick={closeArchive} type="button"><X size={18} /></button></div>
              {archiveError ? <div className="error-summary" role="alert"><strong>{errorMessage(archiveError)}</strong></div> : null}
              {loadingArchiveImpact ? <div className="archive-impact-loading"><LoaderCircle className="spin" size={20} /> {t("loadingData")}</div> : null}
              {archiveImpact ? <>
                <div className="project-archive-warning"><AlertTriangle size={18} /><div><strong>{t("projectsArchivePermanentWarning")}</strong><p>{t("projectsArchivePermanentHelp")}</p></div></div>
                <dl className="archive-impact-grid">
                  <div><dt>{t("projectsArchiveRetainedDocuments")}</dt><dd>{archiveImpact.completed_document_count}</dd></div>
                  <div><dt>{t("projectsArchiveRetainedVersions")}</dt><dd>{archiveImpact.completed_version_count}</dd></div>
                  <div><dt>{t("projectsArchiveDeletedVersions")}</dt><dd>{archiveImpact.unfinished_version_count}</dd></div>
                  <div><dt>{t("projectsArchiveDeletedDocuments")}</dt><dd>{archiveImpact.deleted_document_count}</dd></div>
                  <div><dt>{t("projectsArchiveDeletedFiles")}</dt><dd>{archiveImpact.unfinished_file_count}</dd></div>
                  <div><dt>{t("projectsArchiveDeletedWork")}</dt><dd>{archiveImpact.unfinished_pipeline_count + archiveImpact.unfinished_sync_count + archiveImpact.unfinished_validation_count + archiveImpact.unfinished_approval_count}</dd></div>
                  <div><dt>{t("projectsArchiveDeletedIndexes")}</dt><dd>{archiveImpact.unfinished_staging_index_count + archiveImpact.unfinished_embedding_build_count}</dd></div>
                  <div><dt>{t("projectsArchiveDeletedGraphs")}</dt><dd>{archiveImpact.unfinished_graph_count}</dd></div>
                </dl>
                <label className="archive-confirmation-field"><span>{format("projectsArchiveConfirmationLabel", { name: archiveTarget.name })}</span><input autoComplete="off" onChange={(event) => setArchiveConfirmation(event.target.value)} value={archiveConfirmation} /></label>
              </> : null}
              <div className="modal-actions"><button className="action-button secondary" disabled={archiving} onClick={closeArchive} type="button">{t("cancel")}</button><button className="action-button danger" disabled={!archiveImpact || archiveConfirmation !== archiveTarget.name || archiving} onClick={() => void confirmArchive()} type="button">{archiving ? <LoaderCircle className="spin" size={16} /> : <Archive size={16} />} {archiving ? t("projectsArchiving") : t("projectsArchiveConfirm")}</button></div>
            </section>
          </div>
        ) : null}
      </>}
    </AppShell>
  );
}
