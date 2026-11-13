"use client";

import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ApiFetch, KnowledgeDetailResponse } from "@/lib/api";
import { addChunkTag, addDocumentTag, autoTagChunk, autoTagDocument, deleteChunkTag, deleteDocumentTag } from "@/lib/api";

/** Page dependencies shared with the knowledge tag actions. */
export type KnowledgeTagDeps = {
  apiFetch: ApiFetch;
  params: { id: string; knowledgeId: string };
  liveDetail: KnowledgeDetailResponse | null;
  setLiveDetail: Dispatch<SetStateAction<KnowledgeDetailResponse | null>>;
  setSelectedChunkIds: Dispatch<SetStateAction<string[]>>;
};

export type KnowledgeTagState = ReturnType<typeof useKnowledgeTagState>;

/** Document and chunk tag editing state (split from the knowledge detail page, OPT424-038). */
export function useKnowledgeTagState() {
  const [documentTagDraft, setDocumentTagDraft] = useState("");
  const [chunkTagDrafts, setChunkTagDrafts] = useState<Record<string, string>>({});
  const [tagBusyKey, setTagBusyKey] = useState<string | null>(null);
  const [tagError, setTagError] = useState(false);
  return { documentTagDraft, setDocumentTagDraft, chunkTagDrafts, setChunkTagDrafts, tagBusyKey, setTagBusyKey, tagError, setTagError };
}

/** Document and chunk tag actions, created each render once page dependencies exist. */
export function createKnowledgeTagActions(state: KnowledgeTagState, deps: KnowledgeTagDeps) {
  const { apiFetch, params, liveDetail, setLiveDetail, setSelectedChunkIds } = deps;
  const { documentTagDraft, setDocumentTagDraft, chunkTagDrafts, setChunkTagDrafts, setTagBusyKey, setTagError } = state;

  async function refreshAfterTag(action: () => Promise<KnowledgeDetailResponse>) {
    setTagError(false);
    try {
      const refreshed = await action();
      setLiveDetail(refreshed);
      setSelectedChunkIds((current) => current.length ? current : refreshed.chunks[0]?.id ? [refreshed.chunks[0].id] : []);
    } catch {
      setTagError(true);
    } finally {
      setTagBusyKey(null);
    }
  }

  function addDocumentTagFromDraft() {
    const tagText = documentTagDraft.trim();
    if (!liveDetail || !tagText) return;
    setTagBusyKey("document:add");
    refreshAfterTag(() => addDocumentTag(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, tagText)).then(() => setDocumentTagDraft(""));
  }

  function addChunkTagFromDraft(chunkId: string) {
    const tagText = (chunkTagDrafts[chunkId] ?? "").trim();
    if (!liveDetail || !tagText) return;
    setTagBusyKey(`chunk:${chunkId}:add`);
    refreshAfterTag(() => addChunkTag(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, chunkId, tagText)).then(() => setChunkTagDrafts((current) => ({ ...current, [chunkId]: "" })));
  }

  function autoTagWholeDocument() {
    if (!liveDetail) return;
    setTagBusyKey("document:auto");
    refreshAfterTag(() => autoTagDocument(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id));
  }

  function deleteWholeDocumentTag(tagId: string) {
    if (!liveDetail) return;
    setTagBusyKey(`document:delete:${tagId}`);
    refreshAfterTag(() => deleteDocumentTag(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, tagId));
  }

  function autoTagOneChunk(chunkId: string) {
    if (!liveDetail) return;
    setTagBusyKey(`chunk:${chunkId}:auto`);
    refreshAfterTag(() => autoTagChunk(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, chunkId));
  }

  function deleteOneChunkTag(chunkId: string, tagId: string) {
    if (!liveDetail) return;
    setTagBusyKey(`chunk:${chunkId}:delete:${tagId}`);
    refreshAfterTag(() => deleteChunkTag(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, chunkId, tagId));
  }

  return { addDocumentTagFromDraft, addChunkTagFromDraft, autoTagWholeDocument, deleteWholeDocumentTag, autoTagOneChunk, deleteOneChunkTag };
}
