import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


const read = (path) => readFile(new URL(path, import.meta.url), "utf8");


test("CHG-237 role API uses exact-name soft delete and standalone lifecycle updates", async () => {
  const api = await read("../src/lib/api.ts");

  assert.match(api, /export async function deleteRole/);
  assert.match(api, /new URLSearchParams\(\{ lock_version: String\(lockVersion\), confirmation_name: confirmationName \}\)/);
  assert.match(api, /method: "DELETE"/);
  assert.doesNotMatch(api, /export async function deactivateRole/);
});


test("CHG-237 local role cards expose search status switch menu and exact-name dialog", async () => {
  const [source, css, zh, en] = await Promise.all([
    read("../src/components/SystemManagementWorkspace.tsx"),
    read("../src/app/globals.css"),
    read("../src/i18n/locales/zh.json").then(JSON.parse),
    read("../src/i18n/locales/en.json").then(JSON.parse),
  ]);

  assert.match(source, /const \[roleQuery, setRoleQuery\] = useState\(""\)/);
  assert.match(source, /const \[roleStatusFilter, setRoleStatusFilter\] = useState<RoleStatusFilter>\("all"\)/);
  assert.match(source, /role="switch"/);
  assert.match(source, /aria-checked=\{isActive\}/);
  assert.match(source, /<Ellipsis size=\{18\}/);
  assert.match(source, /modal\.type === "role-delete" \? "alertdialog" : "dialog"/);
  assert.match(source, /roleDeleteConfirmation !== modal\.role\.name/);
  assert.match(source, /modal\.role\.isActive === false \|\| !canEditRoles/);
  assert.match(source, /selectedRoleReadOnly \|\| !enabled/);
  assert.doesNotMatch(source, /t\("systemLocalRole"\)/);

  assert.match(css, /\.system-role-toolbar/);
  assert.match(css, /\.system-role-switch\[aria-checked="true"\]/);
  assert.match(css, /\.system-role-menu button\.destructive/);
  assert.match(css, /\.system-role-card\.inactive/);
  assert.match(css, /@media \(max-width: 720px\)[\s\S]*\.system-role-card-header \{ grid-template-columns: 36px minmax\(0, 1fr\); \}/);

  for (const key of [
    "systemSearchRoles",
    "systemRoleStatusFilter",
    "systemDisableRoleHelp",
    "systemRoleReadOnlyHelp",
    "systemDeleteRoleWarningHelp",
    "systemDeleteRoleConfirmationLabel",
    "systemDeleteRolePermanently",
  ]) {
    assert.ok(zh[key], `missing zh key ${key}`);
    assert.ok(en[key], `missing en key ${key}`);
  }
});
