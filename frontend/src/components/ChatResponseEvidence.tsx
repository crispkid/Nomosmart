"use client";

import Link from "next/link";
import { FileText, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChunkMarkdownView, selectChunkMarkdownSource } from "@/components/ChunkMarkdownView";
import { SafeMarkdown } from "@/components/SafeMarkdown";
import { chunkContentPreview } from "@/lib/documentGraph";
import { useI18n } from "@/lib/i18nClient";
import type { ProjectChatCitation } from "@/lib/api";

type SelectedCitation = { citation: ProjectChatCitation; ordinal: number };

export function chatCitationTitle(
  citation: ProjectChatCitation,
  chunkLabel: (number: number) => string,
  unavailableLabel: string,
) {
  return chunkContentPreview(citation.excerpt)
    ?? (citation.chunk_index !== null && citation.chunk_index !== undefined
      ? chunkLabel(citation.chunk_index)
      : unavailableLabel);
}

export function ChatResponseEvidence({
  answer,
  answerFallback,
  answerLabel,
  citations,
  citationsLabel,
  detailHref,
  idPrefix,
  noCitationsLabel,
  answerContainerClassName,
  citationsContainerClassName = "chat-citations",
}: {
  answer: string | null | undefined;
  answerFallback: string;
  answerLabel?: string;
  citations: ProjectChatCitation[];
  citationsLabel: string;
  detailHref?: string;
  idPrefix: string;
  noCitationsLabel: string;
  answerContainerClassName?: string;
  citationsContainerClassName?: string;
}) {
  const { format, t } = useI18n();
  const [selected, setSelected] = useState<SelectedCitation | null>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const normalizedAnswer = answer || answerFallback;
  const selectedDisplaySource = selected ? selectChunkMarkdownSource({
    content: selected.citation.content,
    display_markdown: selected.citation.display_markdown,
    markdown_content: selected.citation.markdown_content,
  }) : null;

  useEffect(() => {
    if (selected) dialogRef.current?.focus();
  }, [selected]);

  const titles = useMemo(
    () => citations.map((citation) => chatCitationTitle(
      citation,
      (number) => format("chatCitationChunkNumber", { number }),
      t("citationUntitled"),
    )),
    [citations, format, t],
  );

  function openCitation(ordinal: number) {
    const citation = citations[ordinal - 1];
    if (citation) setSelected({ citation, ordinal });
  }

  const answerContent = (
    <SafeMarkdown
      citationCount={citations.length}
      citationLabel={(ordinal) => format("chatCitationMarkerAria", { ordinal })}
      citationMismatchLabel={(ordinal) => format("chatCitationMarkerMismatch", { ordinal })}
      onCitationSelect={openCitation}
      source={normalizedAnswer}
    />
  );

  return (
    <>
      {answerContainerClassName ? (
        <div className={answerContainerClassName}>
          {answerLabel ? <strong>{answerLabel}</strong> : null}
          {answerContent}
        </div>
      ) : answerContent}

      <div className={citationsContainerClassName}>
        <strong>{citationsLabel}</strong>
        {citations.map((citation, index) => {
          const ordinal = index + 1;
          const canonicalLabel = citation.chunk_index !== null && citation.chunk_index !== undefined
            ? format("chatCitationChunkNumber", { number: citation.chunk_index })
            : t("chatCitationChunkNumberUnavailable");
          const metadata = [
            canonicalLabel,
            citation.page ? format("projectChatPageLabel", { page: citation.page }) : null,
            citation.content_type || null,
            citation.score !== null && citation.score !== undefined
              ? format("chatCitationScore", { score: citation.score.toFixed(4) })
              : null,
          ].filter(Boolean).join(" · ");
          return (
            <button
              aria-label={format("chatCitationOpenSourceAria", { ordinal, title: titles[index] })}
              className="chat-citation-card"
              id={`${idPrefix}-citation-${ordinal}`}
              key={`${idPrefix}-${citation.chunk_id}-${ordinal}`}
              onClick={() => openCitation(ordinal)}
              type="button"
            >
              <span aria-hidden="true" className="chat-citation-ordinal">[{ordinal}]</span>
              <FileText aria-hidden="true" size={14} />
              <span className="chat-citation-copy"><strong>{titles[index]}</strong><small>{metadata}</small></span>
            </button>
          );
        })}
        {!citations.length ? <span className="project-live-boundary">{noCitationsLabel}</span> : null}
      </div>

      {selected ? (
        <div className="modal-backdrop" role="presentation">
          <section
            aria-labelledby={`${idPrefix}-citation-dialog-title`}
            aria-modal="true"
            className="modal-panel chat-small-modal"
            ref={dialogRef}
            role="dialog"
            tabIndex={-1}
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">[{selected.ordinal}] · {selected.citation.chunk_index !== null && selected.citation.chunk_index !== undefined ? format("chatCitationChunkNumber", { number: selected.citation.chunk_index }) : t("chatCitationChunkNumberUnavailable")}</p>
                <h2 id={`${idPrefix}-citation-dialog-title`}>{t("citationPreview")}</h2>
              </div>
              <button aria-label={t("closeDialog")} className="icon-button" onClick={() => setSelected(null)} type="button"><X size={18} /></button>
            </div>
            <div className="citation-preview-body">
              <FileText aria-hidden="true" size={20} />
              <div>
                <strong>{titles[selected.ordinal - 1]}</strong>
                {selectedDisplaySource ? (
                  <ChunkMarkdownView
                    chunk={{
                      content: selected.citation.content,
                      display_markdown: selected.citation.display_markdown,
                      markdown_content: selected.citation.markdown_content,
                    }}
                    className="chat-citation-markdown"
                  />
                ) : <p>{selected.citation.excerpt || t("documentChatNoCitationExcerpt")}</p>}
              </div>
            </div>
            <dl className="citation-preview-meta">
              <div><dt>{t("chatCitationSourceOrdinal")}</dt><dd>[{selected.ordinal}]</dd></div>
              <div><dt>{t("labelChunk")}</dt><dd>{selected.citation.chunk_index !== null && selected.citation.chunk_index !== undefined ? format("chatCitationChunkNumber", { number: selected.citation.chunk_index }) : t("chatCitationChunkNumberUnavailable")}</dd></div>
              <div><dt>{t("chatCitationTechnicalId")}</dt><dd>{selected.citation.chunk_id}</dd></div>
              <div><dt>{t("labelVersion")}</dt><dd>{selected.citation.document_version_id}</dd></div>
              <div><dt>{t("labelDocument")}</dt><dd>{selected.citation.document_id}</dd></div>
              <div><dt>{t("labelIndex")}</dt><dd>{selected.citation.index_name || t("citationPublishedIndex")}</dd></div>
            </dl>
            <div className="modal-actions">
              <button className="action-button secondary" onClick={() => setSelected(null)} type="button">{t("closeDialog")}</button>
              {detailHref ? <Link className="action-button" href={detailHref}>{t("openExtraction")}</Link> : null}
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
