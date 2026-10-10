"use client";

import { ImageIcon } from "lucide-react";
import { useMemo, type CSSProperties, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";

import { SafeMarkdown, SafeMarkdownInline } from "@/components/SafeMarkdown";
import type { DocumentLayoutBlock, DocumentLayoutListItem, DocumentLayoutPage, DocumentLayoutSourceFragment } from "@/lib/api";
import type { SourceSelectionGroup } from "@/lib/markdownSourceMapping";
import { SourceRangeHighlights } from "@/components/SourceRangeHighlights";
import { pointerSourceRange } from "@/lib/sourceRangeGeometry";


type DocumentLayoutViewerProps = {
  pages: DocumentLayoutPage[];
  selectedAnchors: Set<string>;
  onSelect: (anchor: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLElement>, anchor: string) => void;
  formatPageLabel: (page: number) => string;
  selectionGroups?: SourceSelectionGroup[];
  canonicalSource?: string;
  onSelectRange?: (range: { start: number; end: number }) => void;
};

function blockAnchor(block: DocumentLayoutBlock) {
  return block.source_anchor ?? block.id;
}

function projectedText(text: string, fragments: DocumentLayoutSourceFragment[], canonical: string[]) {
  if (!canonical.length || !fragments.length) return text;
  const points = Array.from(text);
  if (fragments.length === 1 && fragments[0].text_start_offset == null) {
    const f = fragments[0];
    if (canonical.slice(f.start_offset, f.end_offset).join("") !== text) return text;
    return <span data-source-start={f.start_offset} data-source-end={f.end_offset} data-source-direct="true" data-source-envelopes="[]">{text}</span>;
  }
  const pieces: ReactNode[] = [];
  let cursor = 0;
  for (const f of [...fragments].sort((a, b) => (a.text_start_offset ?? 0) - (b.text_start_offset ?? 0))) {
    const start = f.text_start_offset, end = f.text_end_offset;
    if (start == null || end == null || start < cursor || end <= start || end > points.length) continue;
    if (start > cursor) pieces.push(points.slice(cursor, start).join(""));
    const value = points.slice(start, end).join("");
    pieces.push(<span key={f.fragment_id} data-source-start={f.start_offset} data-source-end={f.end_offset} data-source-direct={canonical.slice(f.start_offset, f.end_offset).join("") === value ? "true" : "false"} data-source-envelopes="[]">{value}</span>);
    cursor = end;
  }
  if (cursor < points.length) pieces.push(points.slice(cursor).join(""));
  return pieces;
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
  onSelectRange,
  canonicalPoints,
}: Omit<DocumentLayoutViewerProps, "pages" | "formatPageLabel" | "selectionGroups"> & { block: DocumentLayoutBlock; gridRow: number; selectedChunkIds: string[]; canonicalPoints: string[] }) {
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
    onClick: (event: MouseEvent<HTMLElement>) => {
      if (window.getSelection()?.isCollapsed === false) return;
      const range = onSelectRange ? pointerSourceRange(event.target, event.clientX, event.clientY) : null;
      if (range) onSelectRange?.(range);
      else onSelect(anchor);
    },
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => onKeyDown(event, anchor),
    role: "button" as const,
    style: { gridColumn: 1, gridRow } satisfies CSSProperties,
    tabIndex: 0,
  };
  const blockText = block.text ?? "";
  const start = block.source_start_offset;
  const end = block.source_end_offset;
  const fragments = block.source_fragments ?? [];
  if (block.type === "code") return <div {...common}><pre><code className={block.code_language ? `language-${block.code_language}` : undefined}>{projectedText(blockText, fragments.filter(f => f.kind === "code"), canonicalPoints)}</code></pre></div>;
  if ((block.continuation_count ?? 1) > 1 && (block.type === "paragraph" || block.type === "blockquote")) {
    const content = projectedText(blockText, fragments.filter(f => f.kind === "text"), canonicalPoints);
    return <div {...common}>{block.type === "blockquote" ? <blockquote>{content}</blockquote> : <p>{content}</p>}</div>;
  }
  if (block.type === "list" && canonicalSource && (block.continuation_count ?? 1) > 1 && fragments.length) {
    const canonical = canonicalPoints;
    return <div {...common}><div className="layout-list-fragments">{listItems(block).map((item, index) => {
      const source = fragments.filter(f => f.kind === "list_item" && f.ordinal_path[0] === index);
      if (source.length === 1 && source[0].text_start_offset == null) {
        const f = source[0];
        return <SafeMarkdown key={f.fragment_id} source={canonical.slice(f.start_offset, f.end_offset).join("")} sourceOffset={f.start_offset} />;
      }
      const value = projectedText(item.text, source, canonicalPoints);
      return block.list_ordered ? <ol key={index} start={item.value ?? block.list_start ?? 1}><li>{value}</li></ol> : <ul key={index}><li>{value}</li></ul>;
    })}</div></div>;
  }
  if (canonicalSource && (block.continuation_count ?? 1) === 1
      && typeof start === "number" && typeof end === "number" && end > start) {
    const raw = canonicalPoints.slice(start, end).join("");
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
    const canonical = canonicalSource ? canonicalPoints : null;
    const cell = (kind: "table_header" | "table_cell", path: number[], fallback: string) => {
      const f = fragments.find(f => f.kind === kind && f.ordinal_path.join(".") === path.join("."));
      return f && canonical && !f.repeated_context
        ? <SafeMarkdownInline source={canonical.slice(f.start_offset, f.end_offset).join("")} sourceOffset={f.start_offset} />
        : <SafeMarkdownInline source={fallback} />;
    };
    return (
      <div {...common}>
        <table>
          {header.length ? <thead><tr>{header.map((value, index) => <th key={`${block.id}-head-${index}`}>{cell("table_header", [index], headerMarkdown[index] || value)}</th>)}</tr></thead> : null}
          <tbody>{block.rows.map((row, rowIndex) => <tr key={`${block.id}-row-${rowIndex}`}>{row.map((value, cellIndex) => <td key={`${block.id}-${rowIndex}-${cellIndex}`}>{cell("table_cell", [rowIndex, cellIndex], rowsMarkdown[rowIndex]?.[cellIndex] || value)}</td>)}</tr>)}</tbody>
        </table>
      </div>
    );
  }
  if (block.type === "image") {
    return <div {...common}><figure><div className="layout-image-placeholder"><ImageIcon size={22} /></div><figcaption>{block.caption ? <SafeMarkdownInline source={block.caption_markdown || block.caption} /> : null}</figcaption></figure></div>;
  }
  if (block.type === "blockquote") return <div {...common}><blockquote><SafeMarkdownInline source={inlineSource} /></blockquote></div>;
  if (block.type === "horizontal_rule") return <div {...common}><hr /></div>;
  return <div {...common}><p><SafeMarkdownInline source={inlineSource} /></p></div>;
}

export function DocumentLayoutViewer({ pages, selectedAnchors, selectionGroups, onSelect, onKeyDown, formatPageLabel, canonicalSource, onSelectRange }: DocumentLayoutViewerProps) {
  const canonicalPoints = useMemo(() => Array.from(canonicalSource ?? ""), [canonicalSource]);
  const effectiveGroups = selectionGroups ?? (selectedAnchors.size ? [{ id: "selected-source", sourceAnchors: [...selectedAnchors], sourceMappings: [] }] : []);
  return <SourceRangeHighlights groups={effectiveGroups}>{pages.map((page) => {
    return (
      <section aria-label={formatPageLabel(page.page_number)} className="document-page structured-layout-page" key={page.page_number}>
        <div className="document-page-content structured-layout-content">
          {page.blocks.map((block, index) => {
            const anchor = blockAnchor(block);
            const selectedChunkIds = effectiveGroups.filter((group) => group.sourceAnchors.includes(anchor)).map((group) => group.id);
            return (
              <LayoutBlockView
                block={block}
                canonicalSource={canonicalSource}
                canonicalPoints={canonicalPoints}
                gridRow={index + 1}
                key={block.id}
                onKeyDown={onKeyDown}
                onSelect={onSelect}
                onSelectRange={onSelectRange}
                selectedAnchors={selectedAnchors}
                selectedChunkIds={selectedChunkIds}
              />
            );
          })}
        </div>
        <footer className="document-page-number">{page.page_number}</footer>
      </section>
    );
  })}</SourceRangeHighlights>;
}
