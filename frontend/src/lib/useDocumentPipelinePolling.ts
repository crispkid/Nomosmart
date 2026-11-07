"use client";

import { useEffect, useRef } from "react";
import type { CreatedKnowledgeDocument as Document } from "../components/KnowledgeSourceModals";
import { getPipelineDetail, type ApiFetch, type PipelineRunDetail } from "./api";
import { isPollingAuthorizationFailure, startFileProcessingPolling } from "./fileProcessingPolling";
import { extractionRunKey, fileObservationMode, type PipelineObservationOwnership } from "./manualExtraction";
import { receiveUploadDocuments } from "./documentList";

type Options = {
  projectId: string;
  enabled: boolean;
  documents: Document[];
  apiFetch: ApiFetch;
  applyDetail: (document: Document, detail: PipelineRunDetail) => Document;
  receive: (documents: Document[]) => void;
  ownership: PipelineObservationOwnership;
};
type Observer = { document: Document; stop: () => void; active: () => boolean };

/** List-owned, GET-only observation. The upload modal owns observation while open. */
export function useDocumentPipelinePolling(options: Options) {
  const current = useRef(options);
  const observers = useRef(new Map<string, Observer>());
  const denied = useRef(new Set<string>());

  useEffect(() => {
    current.current = options;
    const active = new Map(options.enabled ? options.documents.flatMap((document) => {
      const key = extractionRunKey(options.projectId, document);
      return key && fileObservationMode(document) ? [[key, document] as const] : [];
    }) : []);
    for (const [key, observer] of observers.current) {
      const next = active.get(key);
      if (!next || !observer.active()) { observer.stop(); observers.current.delete(key); }
      else observer.document = next;
    }
    for (const [key, document] of active) {
      if (observers.current.has(key) || denied.current.has(key)) continue;
      const lease = options.ownership.acquire(key, "list");
      const cleanupBudget = options.ownership.cleanupBudget;
      const observer: Observer = { document, stop: lease.release, active: lease.active };
      const valid = () => lease.active() && current.current.enabled
        && !denied.current.has(key) && Boolean(fileObservationMode(observer.document))
        && current.current.documents.some((item) => extractionRunKey(current.current.projectId, item) === key
          && Boolean(fileObservationMode(item)));
      const publish = (next: Document) => {
        observer.document = next;
        current.current.receive([next]);
      };
      const stopCleanup = (next: Document) => {
        publish({ ...next, pipeline: { ...next.pipeline, observationInterrupted: true, cleanupObservationStopped: true } });
      };
      if (fileObservationMode(document) === "cleanup" && cleanupBudget.exhausted(key)) {
        stopCleanup(document);
        lease.release();
        continue;
      }
      const stop = startFileProcessingPolling({
        active: valid,
        execution: () => observer.document.pipeline.execution,
        load: () => {
          if (fileObservationMode(observer.document) === "cleanup" && !cleanupBudget.take(key)) {
            throw new Error("pipeline_cleanup_observation_exhausted");
          }
          return getPipelineDetail(current.current.apiFetch, options.projectId,
            document.id, document.latestVersionId!, document.pipeline.id!, lease.signal);
        },
        value: (detail) => {
          if (!valid()) return;
          if (detail.project_id !== options.projectId || detail.document_id !== document.id
            || detail.id !== document.pipeline.id || detail.document_version_id !== document.latestVersionId) {
            throw new Error("pipeline_observation_scope_mismatch");
          }
          const candidate = current.current.applyDetail(observer.document, detail);
          // An older terminal response must not stop an observer of newer work.
          const next = receiveUploadDocuments({ live: [observer.document], created: [] }, [candidate]).live[0];
          if (fileObservationMode(next) === "cleanup" && cleanupBudget.exhausted(key)) stopCleanup(next);
          else publish(next);
        },
        error: (error) => {
          if (!valid()) return;
          const cleanup = fileObservationMode(observer.document) === "cleanup";
          const invalidContract = error instanceof Error && error.message === "file_processing_poll_contract_invalid";
          const next = { ...observer.document, pipeline: { ...observer.document.pipeline, observationInterrupted: true,
            cleanupObservationStopped: cleanup && (cleanupBudget.exhausted(key) || invalidContract || isPollingAuthorizationFailure(error)),
          } };
          if (isPollingAuthorizationFailure(error)) denied.current.add(key);
          publish(next);
        },
      });
      lease.signal.addEventListener("abort", stop, { once: true });
      observer.stop = () => { stop(); lease.release(); };
      observers.current.set(key, observer);
    }
  }, [options]);

  useEffect(() => {
    const entries = observers.current;
    const blocked = denied.current;
    return () => {
      for (const observer of entries.values()) observer.stop();
      entries.clear();
      blocked.clear();
    };
  }, []);
}
