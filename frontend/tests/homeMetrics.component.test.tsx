import { describe, expect, it } from "vitest";

import type { ProjectResponse } from "@/lib/api";
import { countProjectsUpdatedToday, isSameLocalCalendarDay } from "@/lib/homeMetrics";

function project(overrides: Partial<ProjectResponse>): ProjectResponse {
  return {
    id: "project-1",
    name: "Project",
    description: null,
    status: "active",
    llm_model_id: null,
    embedding_model_id: null,
    ocr_model_id: null,
    lock_version: 1,
    archived_at: null,
    archived_by: null,
    archive_cleanup_status: null,
    is_owner: true,
    current_user_project_roles: ["owner"],
    document_count: 0,
    published_version_count: 0,
    last_activity_at: null,
    capabilities: {
      can_upload: true,
      can_update_source: true,
      can_start_extraction: true,
      can_reextract: true,
      can_edit_chunks: true,
      can_create_reference: true,
      can_sync_source: true,
      can_view_graph: true,
      can_submit_review: true,
    },
    ...overrides,
  };
}

describe("HOME-003 live home metrics", () => {
  it("counts only active projects updated on the browser-local calendar day", () => {
    const reference = new Date(2026, 7, 7, 12, 0, 0);
    expect(countProjectsUpdatedToday([
      project({ id: "today-active", last_activity_at: new Date(2026, 7, 7, 9, 0, 0).toISOString() }),
      project({ id: "today-archived", status: "archived", last_activity_at: new Date(2026, 7, 7, 10, 0, 0).toISOString() }),
      project({ id: "yesterday-active", last_activity_at: new Date(2026, 7, 6, 23, 59, 59).toISOString() }),
    ], reference)).toBe(1);
  });

  it("treats missing and invalid activity timestamps as not updated", () => {
    const reference = new Date(2026, 7, 7, 12, 0, 0);
    expect(isSameLocalCalendarDay(null, reference)).toBe(false);
    expect(isSameLocalCalendarDay("not-a-timestamp", reference)).toBe(false);
    expect(countProjectsUpdatedToday([
      project({ id: "missing" }),
      project({ id: "invalid", last_activity_at: "not-a-timestamp" }),
    ], reference)).toBe(0);
  });
});
