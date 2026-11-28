/** Match only known route boundaries, never a coincidental prefix. */
export function workspaceArea(pathname: string | null): string | null {
  if (!pathname) return null;
  const path = pathname.split(/[?#]/, 1)[0];
  if (path === "/") return "/";
  if (path === "/projects" || path.startsWith("/project/")) return "/projects";
  return ["/approve", "/reports", "/system", "/api-docs"].find(area => path === area || path.startsWith(`${area}/`)) ?? null;
}

export function tabIndexForKey(key: string, current: number, count: number): number | null {
  if (count < 1) return null;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  if (key === "ArrowRight") return (current + 1) % count;
  if (key === "ArrowLeft") return (current + count - 1) % count;
  return null;
}

/** CHG-495 UIRD-002: workspace areas in sidebar order, each with the menu permission that shows it. */
export type WorkspaceNavEntry = { href: string; labelKey: "home" | "dashboard" | "approval" | "reports" | "system" | "apiDocs"; shortKey?: "navProjectsShort" | "navApprovalShort"; menu: string | null };

export const workspaceNavEntries: readonly WorkspaceNavEntry[] = [
  { href: "/", labelKey: "home", menu: null },
  { href: "/projects", labelKey: "dashboard", shortKey: "navProjectsShort", menu: "KnowledgeProjects" },
  { href: "/approve", labelKey: "approval", shortKey: "navApprovalShort", menu: null },
  { href: "/reports", labelKey: "reports", menu: "Reports" },
  { href: "/system", labelKey: "system", menu: "SystemManagement" },
  { href: "/api-docs", labelKey: "apiDocs", menu: null },
];

/** Areas the user may open; the backend still authorizes every request behind them. */
export function visibleWorkspaceNav(canView: (menu: string) => boolean): WorkspaceNavEntry[] {
  return workspaceNavEntries.filter(entry => entry.menu === null || canView(entry.menu));
}

/** Mobile bottom bar: Home, Projects, Review as tabs; the rest goes under "More" (M02). */
export const mobileTabAreas: readonly string[] = ["/", "/projects", "/approve"];

export function splitMobileNav<T extends { href: string }>(items: T[]): { tabs: T[]; more: T[] } {
  return { tabs: items.filter(item => mobileTabAreas.includes(item.href)), more: items.filter(item => !mobileTabAreas.includes(item.href)) };
}
