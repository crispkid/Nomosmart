import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ChatHistoryAuthor } from "@/components/ChatHistoryAuthor";
import { ChatRequestEpoch, chatConversationAccess, chatScopeRevoked, mergeChatHistory } from "@/lib/chatConversationAccess";
import { setLocalePreference } from "@/lib/i18nClient";
import type { ProjectChatConversationResponse } from "@/lib/api";

// Direct component/pure transformation inputs, not API/auth/Provider adapters.
const history = (id: string, creator = "actor-a"): ProjectChatConversationResponse => ({
  id, title: "Stored title", message_count: 2, records: [], updated_at: "2026-09-10T01:00:00Z",
  selected_document_version_ids: ["version"], scope_mode: "document_staging",
  created_by_user_id: creator, created_by_display_name: "Same name", is_mine: true,
  can_continue: true, can_evaluate: true, can_delete: true, can_export: true,
});

afterEach(() => { act(() => setLocalePreference("zh", false)); });

describe("CHG-293 creator identity and fail-closed capabilities", () => {
  it("requires both current UUID and server ownership, never the display name", () => {
    expect(chatConversationAccess(history("a"), "actor-a")).toEqual({
      isMine: true, canContinue: true, canDelete: true, canEvaluate: true, canExport: true,
    });
    expect(Object.values(chatConversationAccess(history("b", "actor-b"), "actor-a"))).not.toContain(true);
    expect(Object.values(chatConversationAccess({ ...history("a"), is_mine: false }, "actor-a"))).not.toContain(true);
  });
  it("defaults old/missing API metadata and missing actor to read-only", () => {
    const old = { ...history("a"), created_by_user_id: undefined, is_mine: undefined };
    expect(Object.values(chatConversationAccess(old, "actor-a"))).not.toContain(true);
    expect(Object.values(chatConversationAccess(null, "actor-a"))).not.toContain(true);
    expect(Object.values(chatConversationAccess(history("a")))).not.toContain(true);
  });
  it("retains per-action restrictions on an own expired scope", () => {
    const access = chatConversationAccess({ ...history("a"), can_continue: false, can_export: false }, "actor-a");
    expect(access).toMatchObject({ isMine: true, canContinue: false, canExport: false, canEvaluate: true, canDelete: true });
  });
  it("merges pages by conversation ID without combining authors or records", () => {
    const original = history("a");
    const replacement = { ...original, message_count: 3, updated_at: "2026-09-10T02:00:00Z" };
    const other = history("b", "actor-b");
    const merged = mergeChatHistory([original], [other, replacement]);
    expect(merged).toEqual([replacement, other]);
    expect(original.message_count).toBe(2);
    expect(other.created_by_user_id).toBe("actor-b");
  });
  it("rejects late completions after selection/scope invalidation", () => {
    const epoch = new ChatRequestEpoch();
    const old = epoch.capture();
    expect(epoch.isCurrent(old)).toBe(true);
    epoch.invalidate();
    const latest = epoch.capture();
    expect(epoch.isCurrent(old)).toBe(false);
    expect(epoch.isCurrent(latest)).toBe(true);
    epoch.invalidate();
    expect(epoch.isCurrent(latest)).toBe(false);
  });
  it("discards revoked scopes, but does not confuse another user's readonly conversation with loss of project access", () => {
    for (const code of ["project_scope_denied", "user_disabled", "permission_denied", "project_archived"]) {
      expect(chatScopeRevoked({ code })).toBe(true);
    }
    expect(chatScopeRevoked({ status: 401 })).toBe(true);
    for (const error of [null, "failure", { code: "conversation_read_only" }, { code: "conversation_busy" }]) {
      expect(chatScopeRevoked(error)).toBe(false);
    }
  });
  it("renders a truthful Traditional Chinese author and text readonly label", () => {
    render(<ChatHistoryAuthor name="Wu Justin" isMine={false} readOnly />);
    expect(screen.getByText("姓名：Wu Justin")).toHaveAttribute("title", "Wu Justin");
    expect(screen.getByText("唯讀")).toBeVisible();
    expect(screen.queryByText(/目前使用者/)).toBeNull();
  });
  it("uses a missing-name label instead of guessing current user or email", () => {
    render(<ChatHistoryAuthor name="  " isMine readOnly={false} />);
    expect(screen.getByText("姓名：使用者名稱未提供 · 我")).toBeVisible();
    expect(screen.queryByText("唯讀")).toBeNull();
  });
  it("distinguishes own unavailable continuation from fully readonly foreign history", () => {
    render(<ChatHistoryAuthor name="CHG293 Editor" isMine readOnly />);
    expect(screen.getByText("不可續問")).toBeVisible();
    expect(screen.queryByText("唯讀")).toBeNull();
    act(() => setLocalePreference("en", false));
    expect(screen.getByText("Cannot continue")).toBeVisible();
    expect(screen.queryByText("Read-only")).toBeNull();
  });
  it("supports English and exposes the complete long name accessibly", () => {
    act(() => setLocalePreference("en", false));
    const name = "Long display name ".repeat(20);
    render(<ChatHistoryAuthor name={name} isMine={false} readOnly />);
    expect(screen.getByTitle(name.trim())).toBeVisible();
    expect(screen.getByText("Read-only")).toBeVisible();
  });
});
