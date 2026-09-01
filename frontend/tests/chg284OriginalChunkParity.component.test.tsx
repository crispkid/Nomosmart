import { fireEvent, render, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChunkMarkdownView } from "@/components/ChunkMarkdownView";
import { DocumentLayoutViewer } from "@/components/DocumentLayoutViewer";
import type { DocumentLayoutPage } from "@/lib/api";
import {
  chunkIdsForResolvedSourceAnchor,
  resolvedSourceMappings,
  sourceAnchorsForChunks,
} from "@/lib/markdownSourceMapping";


const paragraphAnchor = "node-0004-paragraph";
const listAnchor = "node-0005-list";
const childAnchors = ["node-0006-item", "node-0007-item", "node-0008-item"];
const displayMarkdown = [
  "本 MaaS 平台旨在打造企業級 AI 推論工廠。架構設計嚴守以下三大核心原則：",
  "",
  "1. **控制與資料平面分離：** 將 API 路由管理與底層 GPU 網路隔離。",
  "2. **適材適用的雙軌推論：** 針對不同模型採取分流部署。",
  "3. **零信任與精準問責：** 全面落實身分委派。",
].join("\n");

const pages: DocumentLayoutPage[] = [{
  page_number: 1,
  width: 794,
  height: 1123,
  blocks: [
    {
      id: paragraphAnchor,
      type: "paragraph",
      source_anchor: paragraphAnchor,
      text: "本 MaaS 平台旨在打造企業級 AI 推論工廠。架構設計嚴守以下三大核心原則：",
      inline_markdown: "本 MaaS 平台旨在打造企業級 AI 推論工廠。架構設計嚴守以下三大核心原則：",
      level: null,
      items: [],
      rows: [],
      caption: null,
      confidence: 1,
      bbox: null,
    },
    {
      id: listAnchor,
      type: "list",
      source_anchor: listAnchor,
      text: null,
      level: null,
      items: ["控制與資料平面分離： 將 API 路由管理與底層 GPU 網路隔離。", "適材適用的雙軌推論： 針對不同模型採取分流部署。", "零信任與精準問責： 全面落實身分委派。"],
      list_ordered: true,
      list_start: 1,
      list_items: [
        { text: "控制與資料平面分離： 將 API 路由管理與底層 GPU 網路隔離。", inline_markdown: "**控制與資料平面分離：** 將 API 路由管理與底層 GPU 網路隔離。", value: 1 },
        { text: "適材適用的雙軌推論： 針對不同模型採取分流部署。", inline_markdown: "**適材適用的雙軌推論：** 針對不同模型採取分流部署。", value: 2 },
        { text: "零信任與精準問責： 全面落實身分委派。", inline_markdown: "**零信任與精準問責：** 全面落實身分委派。", value: 3 },
      ],
      rows: [],
      caption: null,
      confidence: 1,
      bbox: null,
    },
  ],
}];

function mappedChunk(sourceMapping: Record<string, unknown>) {
  return {
    id: "chunk-1",
    sourceMappings: resolvedSourceMappings([sourceMapping]),
  };
}

describe("CHG-284 Original/Chunk range and Markdown parity", () => {
  it("uses every declared renderable anchor for forward and reverse selection", () => {
    const chunk = mappedChunk({
      mapping_status: "resolved",
      offset_unit: "unicode_code_point",
      source_anchor: paragraphAnchor,
      source_anchors: [paragraphAnchor, listAnchor],
      node_ids: [paragraphAnchor, listAnchor, ...childAnchors],
      markdown_start_offset: 64,
      markdown_end_offset: 373,
      anchor_start_offset: 0,
      anchor_end_offset: 64,
    });

    expect([...sourceAnchorsForChunks([chunk], [chunk.id])]).toEqual([paragraphAnchor, listAnchor]);
    expect(chunkIdsForResolvedSourceAnchor([chunk], paragraphAnchor)).toEqual([chunk.id]);
    expect(chunkIdsForResolvedSourceAnchor([chunk], listAnchor)).toEqual([chunk.id]);
    expect(chunkIdsForResolvedSourceAnchor([chunk], childAnchors[0])).toEqual([]);
  });

  it("keeps the node_ids legacy fallback while layout rendering naturally excludes children", () => {
    const chunk = mappedChunk({
      mapping_status: "resolved",
      offset_unit: "unicode_code_point",
      source_anchor: paragraphAnchor,
      node_ids: [paragraphAnchor, listAnchor, ...childAnchors],
      markdown_start_offset: 64,
      markdown_end_offset: 373,
      anchor_start_offset: 0,
      anchor_end_offset: 64,
    });

    const selected = sourceAnchorsForChunks([chunk], [chunk.id]);
    const { container } = render(
      <DocumentLayoutViewer
        formatPageLabel={(page) => `Page ${page}`}
        onKeyDown={vi.fn()}
        onSelect={vi.fn()}
        pages={pages}
        selectedAnchors={selected}
      />,
    );

    expect(container.querySelectorAll(".layout-block.source-active")).toHaveLength(2);
    expect(container.querySelector(`[data-source-anchor="${childAnchors[0]}"]`)).toBeNull();
  });

  it("falls back to legacy node_ids when an additive source_anchors field is empty", () => {
    const chunk = mappedChunk({
      mapping_status: "resolved",
      offset_unit: "unicode_code_point",
      source_anchor: paragraphAnchor,
      source_anchors: [],
      node_ids: [paragraphAnchor, listAnchor],
      markdown_start_offset: 64,
      markdown_end_offset: 373,
      anchor_start_offset: 0,
      anchor_end_offset: 64,
    });

    expect([...sourceAnchorsForChunks([chunk], [chunk.id])]).toEqual([paragraphAnchor, listAnchor]);
  });

  it("renders equivalent paragraph/list/strong semantics and reverse-selects the list block", () => {
    const onSelect = vi.fn();
    const { container, getByTestId } = render(
      <>
        <div data-testid="original">
          <DocumentLayoutViewer
            formatPageLabel={(page) => `Page ${page}`}
            onKeyDown={vi.fn()}
            onSelect={onSelect}
            pages={pages}
            selectedAnchors={new Set([paragraphAnchor, listAnchor])}
          />
        </div>
        <div data-testid="chunk"><ChunkMarkdownView chunk={{ display_markdown: displayMarkdown }} /></div>
      </>,
    );

    const original = getByTestId("original");
    const chunk = getByTestId("chunk");
    expect(within(original).getAllByRole("listitem")).toHaveLength(3);
    expect(within(chunk).getAllByRole("listitem")).toHaveLength(3);
    expect(original.querySelectorAll("ol > li > strong")).toHaveLength(3);
    expect(chunk.querySelectorAll("ol > li > strong")).toHaveLength(3);
    expect(original.querySelector("strong")).toHaveClass("safe-markdown-semantic-strong");
    expect(chunk.querySelector("strong")).toHaveClass("safe-markdown-semantic-strong");
    expect(original.querySelector("ol")).toHaveClass("safe-markdown-semantic-list");
    expect(chunk.querySelector("ol")).toHaveClass("safe-markdown-semantic-list");

    const listBlock = container.querySelector<HTMLElement>(`[data-source-anchor="${listAnchor}"]`);
    expect(listBlock).not.toBeNull();
    fireEvent.click(listBlock!);
    expect(onSelect).toHaveBeenCalledWith(listAnchor);
  });
});
