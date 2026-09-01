import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "../..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

test("CHG-241 exposes Execute without changing AppShell navigation", () => {
  const system = read("frontend/src/components/SystemManagementWorkspace.tsx");
  const api = read("frontend/src/lib/api.ts");
  const css = read("frontend/src/app/globals.css");

  assert.match(api, /PermissionAction = "view" \| "create" \| "edit" \| "delete" \| "execute"/);
  assert.match(api, /can_execute: boolean/);
  assert.match(system, /key: "Project\.ProjectArchive"/);
  assert.match(system, /actions: \["execute"\]/);
  assert.match(system, /permissionActionExecute/);
  assert.match(css, /\.permission-matrix-table tbody td:first-child strong,\s*\.permission-matrix-table tbody td:first-child small\s*\{\s*display: block;\s*\}/);
  assert.match(css, /\.permission-matrix-table tbody td:first-child small\s*\{[^}]*margin-top: 4px;[^}]*line-height: 1\.45;/);
  assert.doesNotMatch(system, /MENU_PROJECT_ARCHIVE/);
});

test("CHG-241 project cards use live discovery and explicit archive actions", () => {
  const page = read("frontend/src/app/projects/page.tsx");
  const api = read("frontend/src/lib/api.ts");
  const css = read("frontend/src/app/globals.css");

  assert.match(page, /PROJECT_PAGE_SIZE = 12/);
  assert.match(page, /window\.setTimeout\(\(\) => \{\s*setQuery\(searchInput\.trim\(\)\)/);
  assert.match(page, /document\.addEventListener\("pointerdown", handlePointerDown\)/);
  assert.match(page, /event\.key !== "Escape"/);
  assert.match(page, /filterButtonRef\.current\?\.focus\(\)/);
  assert.match(page, /page > lastAvailablePage/);
  assert.match(page, /roles: roleFilters/);
  assert.match(page, /modelState: modelFilter === "all"/);
  assert.match(page, /projectSort/);
  assert.match(page, /project\.is_owner \|\| canExecuteArchive/);
  assert.match(page, /className="project-archive-action"/);
  assert.match(api, /response\.headers\.get\("X-Total-Count"\)/);
  assert.match(css, /\.project-card-metrics/);
  assert.match(css, /\.project-filter-popover/);
  assert.match(css, /grid-template-columns: repeat\(2, minmax\(280px, 1fr\)\)/);
  assert.match(css, /min-height: 40px/);
});
