"use client";

import { useCallback, useMemo, useState, type SetStateAction } from "react";
import type { CreatedKnowledgeDocument as Document } from "../components/KnowledgeSourceModals";
import { documentListItems, receiveExtractionReceipt, receivePipelineDocuments, receiveUploadDocuments, refreshDocumentList, uniqueDocuments, type DocumentList } from "./documentList";
import { mergeTerminalChunkCount } from "./terminalChunkCount";
import type { DocumentSummary } from "./api";

/** One atomic state prevents a refresh and an upload callback duplicating an ID. */
export function useDocumentList() {
  const [state, setState] = useState<DocumentList>({ live: [], created: [] });
  const setLiveDocuments = useCallback((action: SetStateAction<Document[]>) => {
    setState((current) => ({ ...current, live: uniqueDocuments(typeof action === "function" ? action(current.live) : action) }));
  }, []);
  const setCreatedImports = useCallback((action: SetStateAction<Document[]>) => {
    setState((current) => ({ ...current, created: uniqueDocuments(typeof action === "function" ? action(current.created) : action) }));
  }, []);
  const replaceLiveDocuments = useCallback((documents: Document[]) => {
    setState((current) => refreshDocumentList(current, documents));
  }, []);
  const updateUploadedDocumentSnapshots = useCallback((documents: Document[]) => {
    setState((current) => receiveUploadDocuments(current, documents));
  }, []);
  const acceptExtractionReceipt = useCallback((expected: Document, receipt: Document) => {
    setState((current) => receiveExtractionReceipt(current, expected, receipt));
  }, []);
  const updatePipelineSnapshots = useCallback((documents: Document[]) => {
    setState((current) => receivePipelineDocuments(current, documents));
  }, []);
  const updateTerminalChunkCount = useCallback((expected: Document, summary: DocumentSummary) => {
    setState((state) => ({ live: state.live.map((item) => mergeTerminalChunkCount(item, expected, summary)),
      created: state.created.map((item) => mergeTerminalChunkCount(item, expected, summary)) }));
  }, []);
  const allDocuments = useMemo(() => documentListItems(state), [state]);
  return { liveDocuments: state.live, createdImports: state.created, allDocuments,
    setLiveDocuments, setCreatedImports, replaceLiveDocuments, updateUploadedDocumentSnapshots, acceptExtractionReceipt, updatePipelineSnapshots, updateTerminalChunkCount };
}
