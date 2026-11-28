/**
 * CHG-495 UIRD-005: a project's colour dot is derived from its id in the frontend (not stored, not
 * editable, D495-02). The same id always maps to the same palette slot; `.project-color-<n>` in
 * globals.css maps each slot to a theme token.
 */
export const projectColorCount = 5;

export function projectColorIndex(projectId: string): number {
  let hash = 0;
  for (const character of projectId) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return hash % projectColorCount;
}

export function projectColorClass(projectId: string): string {
  return `project-color-${projectColorIndex(projectId)}`;
}
