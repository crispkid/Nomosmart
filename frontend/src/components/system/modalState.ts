import type { AIModelResponse, IntegrationClientResponse } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18nClient";
import type { RoleRow, UserRow } from "@/lib/systemManagement";

/** Shared system-management modal model (split from SystemManagementWorkspace, OPT424-038). */
export type ModelRow = { id: string; name: string; type: string; provider: string; endpoint: string | null; default: boolean; status: string; raw?: AIModelResponse };
export type ModalState =
  | { type: "user"; user: UserRow }
  | { type: "role"; role?: RoleRow }
  | { type: "role-users"; role: RoleRow }
  | { type: "mapping"; role: RoleRow }
  | { type: "role-delete"; role: RoleRow }
  | { type: "model"; model?: ModelRow }
  | { type: "model-delete"; model: ModelRow }
  | { type: "api-key-create" }
  | { type: "api-key-manage"; client: IntegrationClientResponse }
  | { type: "confirm"; title: string; message: string; actionLabel: string; successTitle?: TranslationKey; target: { kind: "user" | "role" | "model" | "client"; id: string; expected?: { field: "is_active" | "status"; value: boolean | string } }; run: (accepted: () => void, current: () => boolean) => Promise<void> };

export function modalScope(modal: ModalState | null) {
  if (!modal) return "closed";
  if (modal.type === "confirm") return `${modal.type}:${modal.target.kind}:${modal.target.id}`;
  if ("role" in modal) return `${modal.type}:${modal.role?.id ?? "new"}`;
  if ("model" in modal) return `${modal.type}:${modal.model?.id ?? "new"}`;
  if ("user" in modal) return `${modal.type}:${modal.user.id}`;
  if ("client" in modal) return `${modal.type}:${modal.client.id}`;
  return modal.type;
}
