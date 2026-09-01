import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApplicationAccessDenied } from "@/components/ApplicationAccessDenied";
import { setLocalePreference } from "@/lib/i18nClient";

Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: {
    clear: vi.fn(),
    getItem: vi.fn(() => null),
    key: vi.fn(() => null),
    length: 0,
    removeItem: vi.fn(),
    setItem: vi.fn(),
  },
});


describe("CHG-256 application access denied surface", () => {
  it("shows only safe denial guidance and actions in Traditional Chinese", () => {
    setLocalePreference("zh", false);
    render(
      <ApplicationAccessDenied
        onLogout={vi.fn(async () => undefined)}
        onRecheck={vi.fn(async () => undefined)}
        recheckResult="idle"
        rechecking={false}
        userDisplayName="user02"
      />,
    );

    expect(screen.getByRole("heading", { name: "您目前沒有系統使用權限" })).toBeInTheDocument();
    expect(screen.getByText("user02")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("請聯絡系統管理員");
    expect(screen.getByRole("button", { name: "重新檢查權限" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "登出" })).toBeEnabled();
    expect(screen.queryByText("首頁")).not.toBeInTheDocument();
    expect(screen.queryByText("簽核工作台")).not.toBeInTheDocument();
  });

  it("switches every denial action and status to English without remounting", async () => {
    setLocalePreference("zh", false);
    const user = userEvent.setup();
    const recheck = vi.fn(async () => undefined);
    const { rerender } = render(
      <ApplicationAccessDenied
        onLogout={vi.fn(async () => undefined)}
        onRecheck={recheck}
        recheckResult="denied"
        rechecking={false}
        userDisplayName="user02"
      />,
    );

    await user.selectOptions(screen.getByRole("combobox", { name: "語言切換" }), "en");
    expect(screen.getByRole("heading", { name: "You do not have system access" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Access has not been updated yet");

    rerender(
      <ApplicationAccessDenied
        onLogout={vi.fn(async () => undefined)}
        onRecheck={recheck}
        recheckResult="idle"
        rechecking
        userDisplayName="user02"
      />,
    );
    expect(screen.getByRole("button", { name: "Checking access…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Logout" })).toBeDisabled();
    act(() => setLocalePreference("zh", false));
  });

  it("coalesces recheck and logout interaction at the rendered controls", async () => {
    setLocalePreference("en", false);
    const user = userEvent.setup();
    const recheck = vi.fn(async () => undefined);
    const logout = vi.fn(async () => undefined);
    render(
      <ApplicationAccessDenied
        onLogout={logout}
        onRecheck={recheck}
        recheckResult="idle"
        rechecking={false}
        userDisplayName="user02"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Recheck access" }));
    await user.click(screen.getByRole("button", { name: "Logout" }));
    expect(recheck).toHaveBeenCalledTimes(1);
    expect(logout).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Signing out…" })).toBeDisabled();
    act(() => setLocalePreference("zh", false));
  });
});
