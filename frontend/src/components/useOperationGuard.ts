"use client";

import { useLayoutEffect, useMemo, useSyncExternalStore } from "react";
import { createOperationGuard, type OperationGuardRegistry } from "@/lib/operationGuard";

export function useOperationGuard(scope: string, registry?: OperationGuardRegistry) {
  const guard = useMemo(() => registry?.get(scope) ?? createOperationGuard(scope), [scope, registry]);
  const state = useSyncExternalStore(guard.subscribe, guard.snapshot, guard.snapshot);
  useLayoutEffect(() => {
    registry?.retain(scope, guard); guard.activate();
    return () => { if (registry) registry.release(scope, guard); else guard.dispose(); };
  }, [guard, registry, scope]);
  return { guard, state, blocked: guard.blocked() };
}
