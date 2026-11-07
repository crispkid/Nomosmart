import type { ProjectMemberCandidate, ProjectMemberResponse } from "@/lib/api";


export type { ProjectMemberCandidate } from "@/lib/api";
export type ProjectMemberRole = "owner" | "editor" | "viewer";
export type ProjectMemberOwnerProtection = "last_owner" | "self_owner";


export function projectMemberOwnerProtection(
  member: ProjectMemberResponse,
  members: ProjectMemberResponse[],
  currentUserId: string | null | undefined,
): ProjectMemberOwnerProtection | null {
  if (!member.roles.includes("owner")) return null;
  const ownerCount = members.filter((row) => row.roles.includes("owner")).length;
  if (ownerCount <= 1) return "last_owner";
  if (currentUserId && member.user_id === currentUserId) return "self_owner";
  return null;
}


export function availableProjectMemberCandidates(
  candidates: ProjectMemberCandidate[],
  members: ProjectMemberResponse[],
  pendingUserIds: ReadonlySet<string>,
): ProjectMemberCandidate[] {
  return candidates.filter((candidate) => {
    if (!candidate.is_active || pendingUserIds.has(candidate.id)) return false;
    return !members.some((member) => member.user_id === candidate.id);
  });
}
