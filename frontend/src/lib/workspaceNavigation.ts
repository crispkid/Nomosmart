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
