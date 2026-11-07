import { isMutationResultUnknown } from "./transportError.ts";

export type OperationPhase = "idle" | "submitting" | "unknown" | "accepted" | "read_failed" | "failed";
export type OperationSnapshot = Readonly<{ phase: OperationPhase; checking: boolean; checked: boolean }>;

/** Synchronous dispatch fence. Presentation text never controls mutation eligibility. */
export function createOperationGuard(scope = "native") {
  let state: OperationSnapshot = { phase: "idle", checking: false, checked: false };
  let generation = 0;
  let active = true;
  const listeners = new Set<() => void>();
  const publish = (next: OperationSnapshot) => { state = next; listeners.forEach(listener => listener()); };
  const current = (token: number) => active && token === generation;
  const blocked = () => state.checking || ["submitting", "unknown", "accepted", "read_failed"].includes(state.phase);
  return {
    scope,
    snapshot: () => state,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    activate() { active = true; },
    dispose() { active = false; generation++; },
    suspend() {
      active = false; generation++;
      const phase = state.phase === "submitting" ? "unknown" : state.phase === "accepted" ? "read_failed" : state.phase;
      publish({ phase, checking: false, checked: false });
    },
    current,
    blocked,
    begin() {
      if (!active || blocked()) return null;
      const token = ++generation;
      publish({ phase: "submitting", checking: false, checked: false });
      return token;
    },
    accepted(token: number) {
      if (current(token)) publish({ phase: "accepted", checking: false, checked: false });
    },
    failed(token: number, error: unknown) {
      if (!current(token)) return;
      const phase = state.phase === "accepted" || state.phase === "read_failed" ? "read_failed"
        : isMutationResultUnknown(error) ? "unknown" : "failed";
      publish({ phase, checking: false, checked: false });
    },
    complete(token: number) {
      if (current(token)) { generation++; publish({ phase: "idle", checking: false, checked: false }); }
    },
    beginCheck() {
      if (!active || state.checking || !["unknown", "accepted", "read_failed"].includes(state.phase)) return null;
      publish({ ...state, checking: true, checked: false });
      return generation;
    },
    checked(token: number, confirmed = false) {
      if (!current(token)) return;
      // A successful GET alone never proves the earlier write succeeded.
      if (confirmed) generation++;
      publish({ phase: confirmed ? "idle" : state.phase, checking: false, checked: true });
    },
    checkFailed(token: number) {
      if (current(token)) publish({ ...state, checking: false, checked: false });
    },
  };
}

export type OperationGuard = ReturnType<typeof createOperationGuard>;

/** Login-owned metadata only. Unconfirmed fences survive closing their editor. */
export function createOperationGuardRegistry(owner = "") {
  const guards = new Map<string, OperationGuard>();
  return {
    get(scope: string) {
      let guard = guards.get(scope);
      if (!guard) { guard = createOperationGuard(owner ? `${owner}:${scope}` : scope); guards.set(scope, guard); }
      return guard;
    },
    retain(scope: string, guard: OperationGuard) { guards.set(scope, guard); },
    release(scope: string, guard: OperationGuard) {
      guard.suspend();
      if (["idle", "failed"].includes(guard.snapshot().phase) && guards.get(scope) === guard) guards.delete(scope);
    },
    clear() { for (const guard of guards.values()) guard.dispose(); guards.clear(); },
  };
}

export type OperationGuardRegistry = ReturnType<typeof createOperationGuardRegistry>;
