"use client";

import { ImageIcon } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type ReactNode } from "react";

import { SafeMarkdown, SafeMarkdownInline } from "@/components/SafeMarkdown";
import type { DocumentLayoutBlock, DocumentLayoutListItem, DocumentLayoutPage } from "@/lib/api";
import type { SourceSelectionGroup } from "@/lib/markdownSourceMapping";


type DocumentLayoutViewerProps = {
  pages: DocumentLayoutPage[];
  selectedAnchors: Set<string>;
  onSelect: (anchor: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLElement>, anchor: string) => void;
  formatPageLabel: (page: number) => string;
  selectionGroups?: SourceSelectionGroup[];
  canonicalSource?: string;
};

type PageSelectionFragment = {
  id: string;
  chunkId: string;
  sourceAnchors: string[];
  startRow: number;
  endRow: number;
};

function blockAnchor(block: DocumentLayoutBlock) {
  return block.source_anchor ?? block.id;
}

function pageSelectionFragments(page: DocumentLayoutPage, groups: SourceSelectionGroup[]): PageSelectionFragment[] {
  const anchors = page.blocks.map(blockAnchor);
  return groups.flatMap((group) => {
    const selected = new Set(group.sourceAnchors);
    const fragments: PageSelectionFragment[] = [];
    let start = -1;
    for (let index = 0; index <= anchors.length; index += 1) {
      const included = index < anchors.length && selected.has(anchors[index]);
      if (included && start < 0) start = index;
      if ((!included || index === anchors.length) && start >= 0) {
        const end = index - 1;
        fragments.push({
          id: `${group.id}-page-${page.page_number}-rows-${start + 1}-${end + 1}`,
          chunkId: group.id,
          sourceAnchors: anchors.slice(start, end + 1),
          startRow: start + 1,
          endRow: end + 1,
        });
        start = -1;
      }
    }
    return fragments;
  });
}

function listItems(block: DocumentLayoutBlock): DocumentLayoutListItem[] {
  if (block.list_items?.length) return block.list_items;
  const start = block.list_start ?? 1;
  return block.items.map((text, index) => ({ text, inline_markdown: null, value: start + index, children: [], continuation: false }));
}

function renderListItems(items: DocumentLayoutListItem[], ordered: boolean, keyPrefix: string, start = 1): ReactNode {
  const children = items.map((item, index) => {
    const nestedStart = item.children?.find((child) => child.value)?.value ?? 1;
    const nested = item.children?.length ? renderListItems(item.children, ordered, `${keyPrefix}-${index}`, nestedStart) : null;
    const nestedLists = item.child_lists?.map((childList, childIndex) => (
      <div className="layout-nested-list" key={`${keyPrefix}-${index}-nested-${childIndex}`}>
        {renderListItems(childList.items, childList.ordered, `${keyPrefix}-${index}-nested-${childIndex}`, childList.start)}
      </div>
    ));
    const value = ordered && item.value ? item.value : undefined;
    return (
      <li className={["safe-markdown-semantic-list-item", item.continuation ? "layout-list-item-continuation" : ""].filter(Boolean).join(" ")} key={`${keyPrefix}-${index}`} value={value}>
        <SafeMarkdownInline source={item.inline_markdown || item.text} />
        {nested}
        {nestedLists}
      </li>
    );
  });
  return ordered
    ? <ol className="safe-markdown-semantic-list" start={start === 1 ? undefined : start}>{children}</ol>
    : <ul className="safe-markdown-semantic-list">{children}</ul>;
}

function LayoutBlockView({
  block,
  selectedAnchors,
  selectedChunkIds,
  gridRow,
  onSelect,
  onKeyDown,
  canonicalSource,
}: Omit<DocumentLayoutViewerProps, "pages" | "formatPageLabel" | "selectionGroups"> & { block: DocumentLayoutBlock; gridRow: number; selectedChunkIds: string[] }) {
  const anchor = blockAnchor(block);
  const selected = selectedAnchors.has(anchor);
  const className = `layout-block layout-block-${block.type} markdown-semantic-content source-target${selected ? " source-active" : ""}`;
  const common = {
    "aria-current": selected ? "true" as const : undefined,
    "aria-pressed": selected,
    className,
    "data-continuation-index": block.continuation_index ?? undefined,
    "data-selected-chunk-ids": selectedChunkIds.length ? selectedChunkIds.join(" ") : undefined,
    "data-source-anchor": anchor,
    onClick: () => onSelect(anchor),
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => onKeyDown(event, anchor),
    role: "button" as const,
    style: { gridColumn: 1, gridRow } satisfies CSSProperties,
    tabIndex: 0,
  };
  const blockText = block.text ?? "";
  const start = block.source_start_offset;
  const end = block.source_end_offset;
  if (canonicalSource && (block.continuation_count ?? 1) === 1
      && typeof start === "number" && typeof end === "number" && end > start) {
    const raw = Array.from(canonicalSource).slice(start, end).join("");
    if (raw) return <div {...common}><SafeMarkdown source={raw} sourceOffset={start} /></div>;
  }
  const inlineSource = block.inline_markdown || blockText;
  if (block.type === "heading") {
    const level = Math.min(Math.max(block.level ?? 2, 1), 6);
    if (level === 1) return <div {...common}><h1><SafeMarkdownInline source={inlineSource} /></h1></div>;
    if (level === 2) return <div {...common}><h2><SafeMarkdownInline source={inlineSource} /></h2></div>;
    if (level === 3) return <div {...common}><h3><SafeMarkdownInline source={inlineSource} /></h3></div>;
    if (level === 4) return <div {...common}><h4><SafeMarkdownInline source={inlineSource} /></h4></div>;
    if (level === 5) return <div {...common}><h5><SafeMarkdownInline source={inlineSource} /></h5></div>;
    return <div {...common}><h6><SafeMarkdownInline source={inlineSource} /></h6></div>;
  }
  if (block.type === "list") {
    const ordered = Boolean(block.list_ordered);
    return <div {...common}>{renderListItems(listItems(block), ordered, block.id, block.list_start ?? 1)}</div>;
  }
  if (block.type === "table") {
    const header = block.table_header ?? [];
    const headerMarkdown = block.table_header_markdown ?? [];
    const rowsMarkdown = block.rows_markdown ?? [];
    return (
      <div {...common}>
        <table>
          {header.length ? <thead><tr>{header.map((cell, index) => <th key={`${block.id}-head-${index}`}><SafeMarkdownInline source={headerMarkdown[index] || cell} /></th>)}</tr></thead> : null}
          <tbody>{block.rows.map((row, rowIndex) => <tr key={`${block.id}-row-${rowIndex}`}>{row.map((cell, cellIndex) => <td key={`${block.id}-${rowIndex}-${cellIndex}`}><SafeMarkdownInline source={rowsMarkdown[rowIndex]?.[cellIndex] || cell} /></td>)}</tr>)}</tbody>
        </table>
      </div>
    );
  }
  if (block.type === "image") {
    return <div {...common}><figure><div className="layout-image-placeholder"><ImageIcon size={22} /></div><figcaption>{block.caption ? <SafeMarkdownInline source={block.caption_markdown || block.caption} /> : null}</figcaption></figure></div>;
  }
  if (block.type === "code") {
    const languageClass = block.code_language ? `language-${block.code_language}` : undefined;
    return <div {...common}><pre><code className={languageClass}>{blockText}</code></pre></div>;
  }
  if (block.type === "blockquote") return <div {...common}><blockquote><SafeMarkdownInline source={inlineSource} /></blockquote></div>;
  if (block.type === "horizontal_rule") return <div {...common}><hr /></div>;
  return <div {...common}><p><SafeMarkdownInline source={inlineSource} /></p></div>;
}

export function DocumentLayoutViewer({ pages, selectedAnchors, selectionGroups, onSelect, onKeyDown, formatPageLabel, canonicalSource }: DocumentLayoutViewerProps) {
  const effectiveGroups = selectionGroups ?? (selectedAnchors.size ? [{ id: "selected-source", sourceAnchors: [...selectedAnchors], sourceMappings: [] }] : []);
  return <>{pages.map((page) => {
    const fragments = pageSelectionFragments(page, effectiveGroups);
    return (
      <section aria-label={formatPageLabel(page.page_number)} className="document-page structured-layout-page" key={page.page_number}>
        <div className="document-page-content structured-layout-content">
          {fragments.map((fragment) => (
            <span
              aria-hidden="true"
              className="layout-selection-group"
              data-chunk-id={fragment.chunkId}
              data-fragment-end-row={fragment.endRow}
              data-fragment-start-row={fragment.startRow}
              data-page-number={page.page_number}
              data-source-anchors={fragment.sourceAnchors.join(" ")}
              key={fragment.id}
              style={{ gridColumn: 1, gridRow: `${fragment.startRow} / ${fragment.endRow + 1}` }}
            />
          ))}
          {page.blocks.map((block, index) => {
            const anchor = blockAnchor(block);
            const selectedChunkIds = effectiveGroups.filter((group) => group.sourceAnchors.includes(anchor)).map((group) => group.id);
            return (
              <LayoutBlockView
                block={block}
                canonicalSource={canonicalSource}
                gridRow={index + 1}
                key={block.id}
                onKeyDown={onKeyDown}
                onSelect={onSelect}
                selectedAnchors={selectedAnchors}
                selectedChunkIds={selectedChunkIds}
              />
            );
          })}
        </div>
        <footer className="document-page-number">{page.page_number}</footer>
      </section>
    );
  })}</>;
}
