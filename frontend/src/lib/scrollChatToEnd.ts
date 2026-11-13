/** Respect the live preference on every update; scroll only this thread. */
export function scrollChatToEnd(thread: HTMLElement | null) {
  if (!thread) return;
  const reduce = thread.ownerDocument.defaultView?.matchMedia("(prefers-reduced-motion: reduce)").matches;
  thread.scrollTo({ top: thread.scrollHeight, behavior: reduce ? "auto" : "smooth" });
}
