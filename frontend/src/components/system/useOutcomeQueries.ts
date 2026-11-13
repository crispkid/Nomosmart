"use client";

import type { Dispatch, RefObject, SetStateAction } from "react";
import type { useFeedback } from "@/components/FeedbackProvider";
import type { useOperationGuard } from "@/components/useOperationGuard";
import { getIntegrationClient, getRole, getRoleUsers, getUser, listExternalGroupMappings, listModels, listRoles, type ApiError, type ExternalGroupResponse } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18nClient";
import { formatCount } from "@/lib/numberFormat";
import { MutationOutcomeUnknown } from "@/lib/transportError";
import type { ModalState, ModelRow, SystemReadState } from "./modalState";
import { modelRow } from "./modelHelpers";
import type { ApiKeyState } from "./useApiKeySection";
import type { ModelActions, ModelState, QuickMutationTarget } from "./useModelSection";
import type { RoleActions, RoleState } from "./useRoleSection";
import type { UserActions } from "./useUserSection";
import type { WorkspaceViewDeps } from "./viewDeps";

type OperationGuard = ReturnType<typeof useOperationGuard>["guard"];
/** Workspace values the outcome checks read and update. */
export type OutcomeQueryDeps = Pick<WorkspaceViewDeps, "apiFetch" | "format" | "locale" | "localizedStatus" | "modal" | "setModal" | "t">
  & Pick<RoleActions, "applyMemberSnapshot" | "cacheRoles" | "refreshRolesAndMappings" | "updateMappingProjection">
  & Pick<UserActions, "cacheUsers"> & Pick<ModelActions, "refreshModels">
  & Pick<ApiKeyState, "setIntegrationClients"> & Pick<ModelState, "setModelTableRows"> & Pick<RoleState, "setRoleUsersReadback"> & {
  notify: ReturnType<typeof useFeedback>["notify"];
  modalGuard: OperationGuard;
  quickGuard: OperationGuard;
  quickTarget: RefObject<QuickMutationTarget | null>;
  modalEventId: RefObject<string>;
  modalReceiptId: RefObject<string | null>;
  modalMutationScope: RefObject<string | null>;
  modalSuccess: RefObject<TranslationKey>;
  mappingRows: RefObject<Awaited<ReturnType<typeof listExternalGroupMappings>>>;
  groupRows: RefObject<ExternalGroupResponse[]>;
  systemReadVersions: RefObject<Record<string, number>>;
  systemReadScope: string;
  setReadState: (section: string, state: SystemReadState) => void;
  setDirtyModal: Dispatch<SetStateAction<ModalState | null>>;
  setLiveModels: Dispatch<SetStateAction<ModelRow[]>>;
  setModalError: Dispatch<SetStateAction<string>>;
  setModalQueryMessage: Dispatch<SetStateAction<string>>;
  setModalReadback: Dispatch<SetStateAction<string>>;
  setQuickError: Dispatch<SetStateAction<ApiError | Error | null>>;
  setQuickQueryFailed: Dispatch<SetStateAction<boolean>>;
};

/** Modal and quick-action outcome checks after an uncertain write (split from the workspace, OPT424-038). */
export function createOutcomeQueries(deps: OutcomeQueryDeps) {
  const { apiFetch, applyMemberSnapshot, cacheRoles, cacheUsers, format, groupRows, locale, localizedStatus, mappingRows, modal, modalEventId, modalGuard, modalMutationScope, modalReceiptId, modalSuccess, notify, quickGuard, quickTarget, refreshModels, refreshRolesAndMappings, setDirtyModal, setIntegrationClients, setLiveModels, setModal, setModalError, setModalQueryMessage, setModalReadback, setModelTableRows, setQuickError, setQuickQueryFailed, setReadState, setRoleUsersReadback, systemReadScope, systemReadVersions, t, updateMappingProjection } = deps;

  async function readOutcomeRecord<T>(read: Promise<T>): Promise<T | undefined> {
    try { return await read; }
    catch (error) { if (error && typeof error === "object" && "status" in error && error.status === 404) return undefined; throw error; }
  }

  async function queryModalOutcome() {
    const token = modalGuard.beginCheck(); if (token === null || !modal) return;
    setModalQueryMessage(t("feedbackCheckingOutcome"));
    try {
      const kind = modal.type === "confirm" ? modal.target.kind : ["model", "model-delete"].includes(modal.type) ? "model" : ["role", "role-delete", "role-users", "mapping"].includes(modal.type) ? "role" : modal.type === "user" ? "user" : "client";
      const sameMutation = modalMutationScope.current === modalGuard.scope;
      const targetId = (modal.type === "confirm" ? modal.target.id : "model" in modal ? modal.model?.id : "role" in modal ? modal.role?.id : "user" in modal ? modal.user.id : "client" in modal ? modal.client.id : undefined) ?? (sameMutation && modalGuard.snapshot().phase !== "unknown" ? modalReceiptId.current : undefined);
      let record: { name?: string; display_name?: string | null; is_active?: boolean; status?: string; lock_version?: number; config_version?: number } | undefined;
      let detailReadback = "";
      if (kind === "model") {
        const rows = await listModels(apiFetch); if (!modalGuard.current(token)) return;
        record = rows.find(row => row.id === targetId);
        setLiveModels(rows.map(modelRow)); setModelTableRows(current => current.map(row => { const found = rows.find(item => item.id === row.id); return found ? modelRow(found) : row; }));
      } else if (targetId && kind === "role") {
        const role = await readOutcomeRecord(getRole(apiFetch, targetId)); if (!modalGuard.current(token)) return;
        if (role && (modal.type === "mapping" || modal.type === "role-users")) {
          const members = await getRoleUsers(apiFetch, targetId); if (!modalGuard.current(token)) return;
          const mappings = modal.type === "mapping" ? await listExternalGroupMappings(apiFetch) : null;
          if (!modalGuard.current(token)) return;
          const currentRole = await getRole(apiFetch, targetId); if (!modalGuard.current(token)) return;
          if (role.lock_version !== members.lock_version || currentRole.lock_version !== members.lock_version) throw new Error("snapshot_changed_reload");
          record = currentRole; cacheRoles([currentRole]); applyMemberSnapshot(targetId, members);
          setRoleUsersReadback(members);
          detailReadback = modal.type === "mapping" ? format("adminMemberReadback", { count: formatCount(new Set(members.users.map(user => user.user_id)).size, locale), version: formatCount(members.lock_version, locale) }) : "";
          if (mappings) {
            mappingRows.current = mappings;
            systemReadVersions.current.mappings = (systemReadVersions.current.mappings ?? 0) + 1;
            setReadState("mappings", { scope: systemReadScope, phase: "ready", received: true });
            updateMappingProjection();
            const id = mappings.find(mapping => mapping.role_id === targetId)?.external_group_id;
            const group = groupRows.current.find(group => group.id === id);
            detailReadback += ` · ${format("adminMappingReadback", { group: group?.path || group?.group_name || id || t("systemNotConfigured") })}`;
          }
        } else if (role) { record = role; cacheRoles([role]); }
      } else if (targetId && kind === "user") {
        const user = await readOutcomeRecord(getUser(apiFetch, targetId)); if (!modalGuard.current(token)) return;
        record = user; if (user) cacheUsers([user]);
      } else if (targetId && kind === "client") {
        const client = await readOutcomeRecord(getIntegrationClient(apiFetch, targetId)); if (!modalGuard.current(token)) return;
        record = client; if (client) setIntegrationClients(rows => rows.map(row => row.id === client.id ? client : row));
      }
      const acknowledged = modalGuard.snapshot().phase === "read_failed" || modalGuard.snapshot().phase === "accepted";
      const expected = modal.type === "confirm" ? modal.target.expected : undefined;
      const currentGoalConfirmed = Boolean(record && expected && record[expected.field] === expected.value);
      if (acknowledged || currentGoalConfirmed) {
        modalGuard.checked(token, true); setModalError(""); setDirtyModal(null); setModal(null);
        notify({ id: sameMutation ? modalEventId.current : crypto.randomUUID(), scope: "system", tone: acknowledged && sameMutation ? "success" : "info", title: acknowledged && sameMutation ? modalSuccess.current : "feedbackCurrentStateChecked" });
      } else {
        modalGuard.checked(token);
        setModalQueryMessage(t("feedbackSystemOutcomeChecked"));
        setModalReadback(record ? [format("feedbackCurrentRecord", { name: record.name ?? record.display_name ?? "—", status: record.is_active !== undefined ? t(record.is_active ? "systemEnabled" : "systemDisabled") : localizedStatus(record.status ?? "unknown"), version: record.config_version ?? record.lock_version ?? "—" }), detailReadback].filter(Boolean).join(" · ") : t("feedbackRecordNotFound"));
      }
    } catch {
      if (!modalGuard.current(token)) return;
      modalGuard.checkFailed(token); setModalQueryMessage(t("feedbackOutcomeQueryFailed"));
    }
  }

  async function queryQuickOutcome() {
    const token = quickGuard.beginCheck(); const target = quickTarget.current;
    if (token === null || !target) return;
    setQuickQueryFailed(false);
    try {
      const rows = target.kind === "model" ? await listModels(apiFetch) : await listRoles(apiFetch);
      if (!quickGuard.current(token)) return;
      const row = rows.find(item => item.id === target.id);
      const confirmed = quickGuard.snapshot().phase === "read_failed" || Boolean(row && (target.field === "is_active" ? row.is_active : "is_default" in row && row.is_default) === target.value);
      if (confirmed) {
        if (target.kind === "model") await refreshModels(() => quickGuard.current(token)); else await refreshRolesAndMappings(() => quickGuard.current(token));
        if (!quickGuard.current(token)) return;
        quickGuard.checked(token, true); setQuickError(null);
        notify({ id: crypto.randomUUID(), scope: "system", tone: "info", title: "feedbackCurrentStateChecked" });
      } else { quickGuard.checked(token); setQuickError(new MutationOutcomeUnknown()); }
    } catch (caught) {
      if (!quickGuard.current(token)) return;
      quickGuard.checkFailed(token); setQuickQueryFailed(true); setQuickError(caught as ApiError | Error);
    }
  }

  return { queryModalOutcome, queryQuickOutcome };
}
