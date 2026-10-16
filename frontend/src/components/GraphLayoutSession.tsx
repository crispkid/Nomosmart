"use client";

import { createContext, useContext, useLayoutEffect, type ReactNode } from "react";
import { activateGraphLayoutSession, clearGraphLayoutSession } from "@/lib/graphLayoutCache";

const Session = createContext<string | null>(null);
export function GraphLayoutSession({ identity, children }: { identity: string | null; children: ReactNode }) {
  useLayoutEffect(() => {
    activateGraphLayoutSession(identity);
    return () => clearGraphLayoutSession();
  }, [identity]);
  return <Session.Provider value={identity}>{children}</Session.Provider>;
}
export function useGraphLayoutSession() { return useContext(Session); }
