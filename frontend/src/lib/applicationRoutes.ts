/** The actual App Router page shapes, not authorization or project visibility. */
const STATIC_PROTECTED_PAGES = new Set(["/", "/projects", "/approve", "/reports", "/system", "/api-docs", "/access-denied"]);
const PROJECT_PAGE = /^\/project\/[^/]+\/(?:import|knowledge\/[^/]+(?:\/(?:chat-test|submit-review))?)$/;
const APPROVAL_PAGE = /^\/approve\/[^/]+$/;

export function isProtectedApplicationPage(pathname: string): boolean {
  // Unknown page shapes must reach Next's terminal 404 without initiating OIDC.
  // The same result survives a full remount; a per-component ref cannot do that.
  const path = pathname.length > 1 ? pathname.replace(/\/$/, "") : pathname;
  return STATIC_PROTECTED_PAGES.has(path) || PROJECT_PAGE.test(path) || APPROVAL_PAGE.test(path);
}
