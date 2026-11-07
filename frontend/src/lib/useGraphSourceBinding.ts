"use client";

import { useEffect, useState } from "react";
import { graphSourceDigest } from "./graphLayoutProtocol";

/** The full authorized response is hashed in memory; only its digest is retained. */
export function useGraphSourceBinding(source: unknown | null): string | null {
  const [binding, setBinding] = useState<{ source: unknown; digest: string } | null>(null);
  useEffect(() => {
    if (!source) return;
    let cancelled = false;
    graphSourceDigest(source).then(digest => { if (!cancelled) setBinding({ source, digest }); }).catch(() => { if (!cancelled) setBinding({ source, digest: "unavailable" }); });
    return () => { cancelled = true; };
  }, [source]);
  return binding && binding.source === source ? binding.digest : null;
}
