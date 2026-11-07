import type { ProjectMemberRole } from "@/lib/projectPermissions";


type RoleOption = {
  id: ProjectMemberRole;
  label: string;
};


type ProjectMemberRoleSelectorProps = {
  describedBy?: string;
  disabled?: boolean;
  label: string;
  memberId: string;
  onChange: (role: ProjectMemberRole) => void;
  options: readonly RoleOption[];
  role: ProjectMemberRole;
};


export function ProjectMemberRoleSelector({
  describedBy,
  disabled = false,
  label,
  memberId,
  onChange,
  options,
  role,
}: ProjectMemberRoleSelectorProps) {
  return (
    <fieldset aria-describedby={describedBy} className="project-permission-role-checks" disabled={disabled}>
      <legend className="sr-only">{label}</legend>
      {options.map((option) => (
        <label key={option.id}>
          <input
            checked={role === option.id}
            name={`project-member-role-${memberId}`}
            onChange={() => {
              if (!disabled && option.id !== role) onChange(option.id);
            }}
            type="radio"
            value={option.id}
          />
          <span>{option.label}</span>
        </label>
      ))}
    </fieldset>
  );
}
