"use client";

import { useMemo, useState } from "react";
import { Pagination } from "@/components/Pagination";
import { useI18n } from "@/lib/i18nClient";

/** Chunks per page on the knowledge detail page (OPT424-036, D424-16). */
export const CHUNK_PAGE_SIZE = 50;

export type ChunkPage<T> = { items: T[]; page: number; pageCount: number; total: number; setPage: (page: number) => void };

/**
 * Client-side paging of the chunk list (D424-16). The API still returns every
 * chunk; only rendering is paged. When the first selected chunk is not on the
 * current page (a new selection or a reload after an action), the list moves to
 * the page that holds it; after a reload that shrinks the list it stays in range.
 */
export function useChunkPage<T extends { id: string }>(chunks: T[], selectedChunkIds: string[], pageSize = CHUNK_PAGE_SIZE): ChunkPage<T> {
  const [page, setPage] = useState(1);
  const target = selectedChunkIds[0];
  // Adjust the page during render (not in an effect) so the target card is in
  // the DOM in the same commit as the selection; the page's scroll-into-view
  // runs on the next animation frame and must find it.
  const [anchor, setAnchor] = useState<{ target: string | undefined; chunks: T[] }>({ target, chunks });
  if (anchor.target !== target || anchor.chunks !== chunks) {
    setAnchor({ target, chunks });
    const index = target ? chunks.findIndex((chunk) => chunk.id === target) : -1;
    if (index >= 0 && Math.floor(index / pageSize) + 1 !== page) setPage(Math.floor(index / pageSize) + 1);
  }
  const pageCount = Math.max(1, Math.ceil(chunks.length / pageSize));
  const current = Math.min(page, pageCount);
  const items = useMemo(() => chunks.slice((current - 1) * pageSize, current * pageSize), [chunks, current, pageSize]);
  return { items, page: current, pageCount, total: chunks.length, setPage };
}

/** Pager shown under the chunk list only when there is more than one page. */
export function ChunkListPager({ chunkPage }: { chunkPage: Pick<ChunkPage<unknown>, "page" | "pageCount" | "total" | "setPage"> }) {
  const { t, format } = useI18n();
  const { page, pageCount, total, setPage } = chunkPage;
  if (pageCount <= 1) return null;
  return (
    <Pagination
      canNext={page < pageCount}
      canPrevious={page > 1}
      className="report-pagination chunk-pagination"
      label={t("knowledgeChunkPagination")}
      nextLabel={t("knowledgeChunkNextPage")}
      onNext={() => setPage(Math.min(page + 1, pageCount))}
      onPrevious={() => setPage(Math.max(page - 1, 1))}
      previousLabel={t("knowledgeChunkPreviousPage")}
      summary={format("knowledgeChunkPageSummary", { page, total: pageCount, count: total })}
    />
  );
}
