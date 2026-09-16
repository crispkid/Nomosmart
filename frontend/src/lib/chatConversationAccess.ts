import type { ProjectChatConversationResponse } from "@/lib/api";

export function chatConversationAccess(item: ProjectChatConversationResponse | null | undefined, actorId?: string) {
  const isMine = Boolean(actorId && item?.created_by_user_id === actorId && item.is_mine === true);
  return {
    isMine,
    canContinue: isMine && item?.can_continue === true,
    canDelete: isMine && item?.can_delete === true,
    canEvaluate: isMine && item?.can_evaluate === true,
    canExport: isMine && item?.can_export === true,
  };
}

export function mergeChatHistory(current: ProjectChatConversationResponse[], incoming: ProjectChatConversationResponse[]) {
  const byId = new Map(current.map((item) => [item.id, item]));
  for (const item of incoming) byId.set(item.id, item);
  return [...byId.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at) || b.id.localeCompare(a.id));
}

// Generation is local UI state, never an authorization credential. Invalidate
// synchronously on selection/scope change before an asynchronous result lands.
export class ChatRequestEpoch {
  private generation = 0;
  capture() { return this.generation; }
  invalidate() { this.generation += 1; }
  isCurrent(generation: number) { return this.generation === generation; }
}

export function chatScopeRevoked(error: unknown) {
  if (!error || typeof error !== "object") return false;
  const value = error as { status?: number; code?: string };
  return value.status === 401 || ["project_scope_denied", "permission_denied", "user_disabled", "user_not_synchronized", "application_access_denied", "project_archived", "project_not_found"].includes(value.code ?? "");
}
