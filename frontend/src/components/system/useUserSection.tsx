"use client";

import { useState } from "react";
import { updateUser, updateUserStatus, type ApiFetch, type UserSummary } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18nClient";
import { userRow, type UserRow } from "@/lib/systemManagement";
import type { ModalState } from "./modalState";

/** Workspace dependencies shared with the user section. */
export type UserDeps = {
  apiFetch: ApiFetch;
  modal: ModalState | null;
  runModalMutation: <T>(write: (accepted: () => void, current: () => boolean) => Promise<T>, apply: (result: T, current: () => boolean) => void | Promise<void>, title?: TranslationKey) => Promise<void>;
};

export type UserState = ReturnType<typeof useUserState>;

/** User maintenance state (split from SystemManagementWorkspace, OPT424-038). */
export function useUserState() {
  const [liveUsers, setLiveUsers] = useState<UserRow[]>([]);
  const [userTableIds, setUserTableIds] = useState<string[]>([]);
  const [userTotal, setUserTotal] = useState(0);
  const [userOverallTotal, setUserOverallTotal] = useState<number | null>(null);
  const [userPage, setUserPage] = useState(1);
  const [userPageSize, setUserPageSize] = useState(20);
  const [userQuery, setUserQuery] = useState("");
  const [userSourceFilter, setUserSourceFilter] = useState("all");
  return { liveUsers, setLiveUsers, userTableIds, setUserTableIds, userTotal, setUserTotal, userOverallTotal, setUserOverallTotal, userPage, setUserPage, userPageSize, setUserPageSize, userQuery, setUserQuery, userSourceFilter, setUserSourceFilter };
}

/** User maintenance actions, created each render once workspace dependencies exist. */
export function createUserActions(state: UserState, deps: UserDeps) {
  const { liveUsers, setLiveUsers, userTableIds, setUserTableIds, userTotal, setUserTotal, userOverallTotal, setUserOverallTotal, userPage, setUserPage, userPageSize, setUserPageSize, userQuery, setUserQuery, userSourceFilter, setUserSourceFilter } = state;

  function cacheUsers(rows: UserSummary[]) {
    setLiveUsers(current => {
      const map = new Map(current.map(row => [row.id, row]));
      rows.forEach(user => map.set(user.id, userRow(user)));
      return [...map.values()];
    });
  }

  async function submitUser(formData: FormData) {
    const { apiFetch, modal, runModalMutation } = deps;
    if (modal?.type !== "user") return;
    const payload: Parameters<typeof updateUser>[2] = {
      knowledge_owner: formData.get("knowledge_owner") === "on", system_notes: String(formData.get("system_notes") || "")
    };
    const baseline = modal.user.raw?.manager_delegate_user_id;
    if (baseline !== undefined && formData.has("manager_delegate_user_id")) {
      const selected = String(formData.get("manager_delegate_user_id") || "").trim() || null;
      if (selected !== baseline) payload.manager_delegate_user_id = selected;
    }
    await runModalMutation(() => updateUser(apiFetch, modal.user.id, payload), updated => { setLiveUsers(current => current.map(user => user.id === updated.id ? userRow(updated) : user)); }, "systemUserLocalFieldsSaved");
  }

  async function toggleUser(user: UserRow, accepted: () => void) {
    const { apiFetch } = deps;
    const next = user.status !== "active";
    const updated = await updateUserStatus(apiFetch, user.id, next); accepted();
    setLiveUsers((current) => current.map((item) => item.id === user.id ? { ...item, status: updated.is_active ? "active" : "inactive", raw: updated } : item));
  }

  return { cacheUsers, submitUser, toggleUser };
}
