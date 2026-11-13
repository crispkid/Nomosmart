"use client";

import { Check, Copy, LoaderCircle } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "@/lib/i18nClient";

type CopyState = "idle" | "copying" | "success" | "error";

export function ApiCodeExample({ code, title }: { code: string; title: string }) {
  const { format, t } = useI18n();
  const [state, setState] = useState<CopyState>("idle");
  const sequence = useRef(0);
  const pending = useRef(false);
  const codeId = useId();
  const statusId = useId();

  useEffect(() => () => { sequence.current += 1; }, []);

  async function copy() {
    if (pending.current) return;
    pending.current = true;
    const request = ++sequence.current;
    setState("copying");
    try {
      await navigator.clipboard.writeText(code);
      if (request === sequence.current) setState("success");
    } catch {
      if (request === sequence.current) setState("error");
    } finally {
      if (request === sequence.current) pending.current = false;
    }
  }

  const Icon = state === "copying" ? LoaderCircle : state === "success" ? Check : Copy;
  const status = state === "copying" ? t("apiDocsCopying")
    : state === "success" ? t("apiDocsCopySuccess")
      : state === "error" ? t("apiDocsCopyFailed") : "";

  return (
    <div className="api-code-example">
      <div className="api-code-toolbar">
        <p className={`api-code-status${state === "error" ? " is-error" : ""}`} id={statusId} role="status">{status}</p>
        <button
          aria-controls={codeId}
          aria-describedby={statusId}
          aria-label={format("apiDocsCopyNamed", { section: title })}
          className="api-code-copy"
          disabled={state === "copying"}
          onClick={() => { void copy(); }}
          type="button"
        >
          <Icon aria-hidden="true" className={state === "copying" ? "spin" : undefined} size={16} />
          {state === "copying" ? t("apiDocsCopying") : t("apiDocsCopyExample")}
        </button>
      </div>
      <pre id={codeId}><code>{code}</code></pre>
    </div>
  );
}
