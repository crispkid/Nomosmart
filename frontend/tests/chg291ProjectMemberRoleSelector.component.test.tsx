import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProjectMemberRoleSelector } from "@/components/ProjectMemberRoleSelector";


const options = [
  { id: "owner" as const, label: "Owner" },
  { id: "editor" as const, label: "編輯者" },
  { id: "viewer" as const, label: "檢視者" },
];


describe("CHG-291 ProjectMemberRoleSelector", () => {
  it("presents exactly one checked role and sends one replacement role", () => {
    const onChange = vi.fn();
    const view = render(
      <ProjectMemberRoleSelector
        label="專案角色"
        memberId="user02"
        onChange={onChange}
        options={options}
        role="editor"
      />,
    );

    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
    expect(radios.filter((radio) => (radio as HTMLInputElement).checked)).toHaveLength(1);
    expect(screen.getByRole("radio", { name: "編輯者" })).toBeChecked();

    fireEvent.click(screen.getByRole("radio", { name: "檢視者" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("viewer");

    view.rerender(
      <ProjectMemberRoleSelector
        label="專案角色"
        memberId="user02"
        onChange={onChange}
        options={options}
        role="viewer"
      />,
    );
    expect(screen.getByRole("radio", { name: "檢視者" })).toBeChecked();
    expect(screen.getAllByRole("radio").filter((radio) => (radio as HTMLInputElement).checked)).toHaveLength(1);
  });

  it("keeps every protected Owner choice read-only", () => {
    const onChange = vi.fn();
    render(
      <ProjectMemberRoleSelector
        describedBy="owner-protection"
        disabled
        label="專案角色"
        memberId="owner01"
        onChange={onChange}
        options={options}
        role="owner"
      />,
    );

    for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "編輯者" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
