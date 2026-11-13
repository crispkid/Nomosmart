import { listProjectsPage, type ApiFetch, type ProjectResponse } from "@/lib/api";

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

export type HomeProjectMetrics = { recent: ProjectResponse[]; activeTotal: number; updatedToday: number };

/**
 * Home KPIs without loading every project (OPT424-035): the active total comes from the list's
 * X-Total-Count, and active projects updated today are counted by reading the list newest-first
 * only until activity falls before the reference day. `recent` is the first three projects.
 */
export async function readHomeProjectMetrics(apiFetch: ApiFetch, reference = new Date(), signal?: AbortSignal, pageSize = 50): Promise<HomeProjectMetrics> {
  const dayStart = new Date(reference);
  dayStart.setHours(0, 0, 0, 0);
  let offset = 0;
  let activeTotal = 0;
  let updatedToday = 0;
  let recent: ProjectResponse[] = [];
  for (;;) {
    const page = await listProjectsPage(apiFetch, { status: "active", sort: "updated_desc", offset, limit: pageSize, signal });
    if (offset === 0) {
      activeTotal = page.total;
      recent = page.items.slice(0, 3);
    }
    updatedToday += countProjectsUpdatedToday(page.items, reference);
    offset += page.items.length;
    const last = page.items.at(-1);
    if (!last || offset >= page.total || !last.last_activity_at || new Date(last.last_activity_at) < dayStart) break;
  }
  return { recent, activeTotal, updatedToday };
}

