import type { PermissionMatrixResponse } from "@/lib/api";
import type { RoleRow } from "@/lib/systemManagement";

/** Permission matrix definitions and role list types for system management (OPT424-038). */
export const permissionMenuRows = [
  { key: "Menu.KnowledgeProjects", moduleName: "Menu", functionName: "KnowledgeProjects", labelKey: "systemMenuKnowledgeProjects", descriptionKey: "systemMenuKnowledgeProjectsHelp", actions: ["view", "create"] },
  { key: "Menu.Reports", moduleName: "Menu", functionName: "Reports", labelKey: "systemMenuReports", descriptionKey: "systemMenuReportsHelp", actions: ["view"] },
  { key: "Menu.SystemManagement", moduleName: "Menu", functionName: "SystemManagement", labelKey: "systemMenuSystemManagement", descriptionKey: "systemMenuSystemManagementHelp", actions: ["view", "create", "edit", "delete"] },
  { key: "Project.ProjectArchive", moduleName: "Project", functionName: "ProjectArchive", labelKey: "systemProjectArchive", descriptionKey: "systemProjectArchiveHelp", actions: ["execute"] },
  { key: "Report.ModelReport", moduleName: "Report", functionName: "ModelReport", labelKey: "systemReportModelReport", descriptionKey: "systemReportModelReportHelp", actions: ["view"] }
] as const;

export type PermissionAction = "view" | "create" | "edit" | "delete" | "execute";

export type PermissionState = Record<string, Record<PermissionAction, boolean>>;

export type RoleStatusFilter = "all" | "enabled" | "disabled";

export type GroupMappingRow = { groupId: string; roleId: string; group: string; source: string; role: string; members: number | null };

export function emptyPermissionState(): PermissionState {
  return Object.fromEntries(permissionMenuRows.map((row) => [row.key, { view: false, create: false, edit: false, delete: false, execute: false }]));
}

export function permissionStateFromResponse(response: PermissionMatrixResponse): PermissionState {
  const state = emptyPermissionState();
  for (const permission of response.permissions) {
    const key = `${permission.module_name}.${permission.function_name}`;
    state[key] = { view: permission.can_view, create: permission.can_create, edit: permission.can_edit, delete: permission.can_delete, execute: permission.can_execute };
  }
  return state;
}

export function permissionPayload(role: RoleRow, state: PermissionState): PermissionMatrixResponse {
  return {
    lock_version: role.lockVersion,
    permissions: permissionMenuRows.map((row) => {
      const value = state[row.key] ?? emptyPermissionState()[row.key];
      const actionSet = new Set<PermissionAction>(row.actions);
      return { module_name: row.moduleName, function_name: row.functionName, can_view: actionSet.has("view") && value.view, can_create: actionSet.has("create") && value.create, can_edit: actionSet.has("edit") && value.edit, can_delete: actionSet.has("delete") && value.delete, can_execute: actionSet.has("execute") && value.execute };
    })
  };
}
