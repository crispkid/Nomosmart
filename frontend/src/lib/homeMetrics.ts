import type { ProjectResponse } from "@/lib/api";

export function localCalendarDayKey(value: Date) {
  return `${value.getFullYear()}-${value.getMonth()}-${value.getDate()}`;
}

export function isSameLocalCalendarDay(value: string | null | undefined, reference: Date) {
  if (!value) return false;
  const timestamp = new Date(value);
  return !Number.isNaN(timestamp.getTime()) && localCalendarDayKey(timestamp) === localCalendarDayKey(reference);
}

export function countProjectsUpdatedToday(projects: ProjectResponse[], reference = new Date()) {
  return projects.filter((project) => project.status === "active" && isSameLocalCalendarDay(project.last_activity_at, reference)).length;
}
