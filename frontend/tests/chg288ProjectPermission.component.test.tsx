import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  availableProjectMemberCandidates,
  projectMemberOwnerProtection,
  type ProjectMemberCandidate,
} from "@/lib/projectPermissions";
import { useDebouncedProjectMemberCandidateSearch } from "@/lib/useDebouncedProjectMemberCandidateSearch";
import type { ProjectMemberCandidatePage, ProjectMemberResponse } from "@/lib/api";


const candidate = (id: string): ProjectMemberCandidate => ({
  id,
  employee_id: `Z-${id}`,
  email: `${id}@nomosmart.test`,
  given_name: id,
  family_name: "User",
  display_name: `User ${id}`,
  is_active: true,
});

const member = (id: string, roles: string[]): ProjectMemberResponse => ({
  user_id: id,
  given_name: id,
  family_name: "User",
  display_name: `User ${id}`,
  email: `${id}@nomosmart.test`,
  roles,
});

const page = (id: string): ProjectMemberCandidatePage => ({
  items: [candidate(id)],
  total: 1,
  offset: 0,
  limit: 20,
  ineligible_match_count: 0,
});

describe("CHG-288 project member permission policy", () => {
  it("protects the sole Owner and the signed-in Owner's own row", () => {
    expect(projectMemberOwnerProtection(member("owner-1", ["owner"]), [member("owner-1", ["owner"])], "owner-1")).toBe("last_owner");

    const members = [member("owner-1", ["owner"]), member("owner-2", ["owner"])];
    expect(projectMemberOwnerProtection(members[0], members, "owner-1")).toBe("self_owner");
    expect(projectMemberOwnerProtection(members[1], members, "owner-1")).toBeNull();
    expect(projectMemberOwnerProtection(member("editor", ["editor"]), members, "editor")).toBeNull();
  });

  it("excludes every existing Project member and pending duplicate from add candidates", () => {
    const candidates = [candidate("user01"), candidate("user02"), candidate("user03")];
    const members = [member("user01", ["owner"]), member("user02", ["viewer"])];
    expect(availableProjectMemberCandidates(candidates, members, new Set(["user03"])).map((row) => row.id)).toEqual([]);
    expect(availableProjectMemberCandidates(candidates, members, new Set()).map((row) => row.id)).toEqual(["user03"]);
  });
});

describe("CHG-288 debounced project member candidate search", () => {
  it("waits for the debounce and lets only the latest request update state", async () => {
    vi.useFakeTimers();
    const resolvers = new Map<string, (result: ProjectMemberCandidatePage) => void>();
    const search = vi.fn((query: string, _signal: AbortSignal) => new Promise<ProjectMemberCandidatePage>((resolve) => {
      resolvers.set(query, resolve);
    }));

    const view = renderHook(
      ({ query }) => useDebouncedProjectMemberCandidateSearch({ enabled: true, query, search, delayMs: 300 }),
      { initialProps: { query: "user0" } },
    );
    expect(view.result.current.phase).toBe("waiting");
    expect(search).not.toHaveBeenCalled();

    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(search).toHaveBeenCalledTimes(1);
    expect(search.mock.calls[0][0]).toBe("user0");
    expect(view.result.current.phase).toBe("loading");

    view.rerender({ query: "user02" });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(search).toHaveBeenCalledTimes(2);

    await act(async () => { resolvers.get("user0")?.(page("stale")); });
    expect(view.result.current.result).toBeNull();
    expect(view.result.current.phase).toBe("loading");

    await act(async () => { resolvers.get("user02")?.(page("user02")); });
    expect(view.result.current.phase).toBe("ready");
    expect(view.result.current.result?.items[0].id).toBe("user02");
    vi.useRealTimers();
  });

  it("reports failure and resets to idle for an empty query", async () => {
    vi.useFakeTimers();
    const search = vi.fn(async () => { throw new Error("candidate search failed"); });
    const view = renderHook(
      ({ query }) => useDebouncedProjectMemberCandidateSearch({ enabled: true, query, search, delayMs: 300 }),
      { initialProps: { query: "user05" } },
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(view.result.current.phase).toBe("error");
    expect(view.result.current.error?.message).toBe("candidate search failed");

    view.rerender({ query: "   " });
    expect(view.result.current.phase).toBe("idle");
    expect(view.result.current.error).toBeNull();
    vi.useRealTimers();
  });
});
