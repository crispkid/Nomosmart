import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProjectMemberAutocomplete } from "@/components/ProjectMemberAutocomplete";
import type { ProjectMemberCandidate } from "@/lib/api";


const candidate = (index: number): ProjectMemberCandidate => ({
  id: `user-${index}`,
  employee_id: `Z00000010${index}`,
  email: `user0${index}@nomosmart.test`,
  given_name: `User${index}`,
  family_name: "Test",
  display_name: `Test User${index}`,
  is_active: true,
});

const defaultProps = {
  candidates: Array.from({ length: 6 }, (_, index) => candidate(index + 1)),
  disabled: false,
  id: "member-search",
  label: "搜尋使用者",
  locale: "zh" as const,
  onQueryChange: vi.fn(),
  onSelect: vi.fn(),
  placeholder: "輸入姓名、Email 或員工編號",
  statusMessage: "",
  value: "user",
};


describe("CHG-289 ProjectMemberAutocomplete", () => {
  it("does not infer the first result and selects only the keyboard-active option", () => {
    const onSelect = vi.fn();
    render(<ProjectMemberAutocomplete {...defaultProps} onSelect={onSelect} />);

    const input = screen.getByRole("combobox", { name: "搜尋使用者" });
    fireEvent.focus(input);
    expect(screen.getAllByRole("option")).toHaveLength(6);

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const options = screen.getAllByRole("option");
    expect(input).toHaveAttribute("aria-activedescendant", "member-search-option-user-2");
    expect(options[1]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "user-2" }));
  });

  it("supports explicit pointer selection and Escape without trapping focus", () => {
    const onSelect = vi.fn();
    render(<ProjectMemberAutocomplete {...defaultProps} onSelect={onSelect} />);

    const input = screen.getByRole("combobox", { name: "搜尋使用者" });
    fireEvent.focus(input);
    const option = screen.getAllByRole("option")[4];
    fireEvent.pointerDown(option);
    fireEvent.click(option);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "user-5" }));

    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(input);
  });

  it("renders a truthful empty state without an option or inferred identity", () => {
    const onSelect = vi.fn();
    render(
      <ProjectMemberAutocomplete
        {...defaultProps}
        candidates={[]}
        onSelect={onSelect}
        statusMessage="找不到符合條件的使用者。"
        value="not-a-user"
      />,
    );

    fireEvent.focus(screen.getByRole("combobox", { name: "搜尋使用者" }));
    expect(screen.getByRole("status")).toHaveTextContent("找不到符合條件的使用者。");
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("reports query changes and clears keyboard activation for the new result set", () => {
    const onQueryChange = vi.fn();
    const view = render(<ProjectMemberAutocomplete {...defaultProps} onQueryChange={onQueryChange} />);
    const input = screen.getByRole("combobox", { name: "搜尋使用者" });
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant");

    fireEvent.change(input, { target: { value: "user02" } });
    expect(onQueryChange).toHaveBeenCalledWith("user02");
    view.rerender(<ProjectMemberAutocomplete {...defaultProps} onQueryChange={onQueryChange} value="user02" />);
    expect(input).not.toHaveAttribute("aria-activedescendant");
  });
});
