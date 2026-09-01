import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CanonicalMarkdownSource } from "@/components/CanonicalMarkdownSource";
import { DocumentLayoutViewer } from "@/components/DocumentLayoutViewer";
import type { DocumentLayoutPage } from "@/lib/api";
import {
  sourceSelectionGroupsForChunks,
  type MarkdownMappedChunk,
} from "@/lib/markdownSourceMapping";


const paragraph = "node-paragraph";
const list = "node-list";

const pages: DocumentLayoutPage[] = [{
  page_number: 1,
  width: 794,
  height: 1123,
  blocks: [
    { id: paragraph, type: "paragraph", source_anchor: paragraph, text: "Intro", level: null, items: [], rows: [], caption: null, confidence: 1, bbox: null },
    { id: list, type: "list", source_anchor: list, text: null, level: null, items: ["One", "Two"], list_ordered: true, list_start: 1, rows: [], caption: null, confidence: 1, bbox: null },
  ],
}];

const chunks: MarkdownMappedChunk[] = [{
  id: "chunk-1",
  sourceMappings: [{
    sourceAnchor: paragraph,
    sourceAnchors: [paragraph, list],
    markdownStart: 4,
    markdownEnd: 24,
    anchorStart: 0,
    anchorEnd: 5,
  }],
}];

describe("CHG-285 one Chunk one visual selection group", () => {
  it("derives deterministic Chunk-level group identity without losing anchors or ranges", () => {
    expect(sourceSelectionGroupsForChunks(chunks, ["chunk-1", "missing"])).toEqual([{
      id: "chunk-1",
      sourceAnchors: [paragraph, list],
      sourceMappings: chunks[0].sourceMappings,
    }]);
  });

  it("renders adjacent Original anchors inside one page-local visual enclosure", () => {
    const onSelect = vi.fn();
    const groups = sourceSelectionGroupsForChunks(chunks, ["chunk-1"]);
    const { container } = render(
      <DocumentLayoutViewer
        formatPageLabel={(page) => `Page ${page}`}
        onKeyDown={vi.fn()}
        onSelect={onSelect}
        pages={pages}
        selectedAnchors={new Set([paragraph, list])}
        selectionGroups={groups}
      />,
    );

    const enclosure = container.querySelector<HTMLElement>('.layout-selection-group[data-chunk-id="chunk-1"]');
    expect(enclosure).not.toBeNull();
    expect(enclosure).toHaveAttribute("data-fragment-start-row", "1");
    expect(enclosure).toHaveAttribute("data-fragment-end-row", "2");
    expect(enclosure?.style.gridRow).toBe("1 / 3");
    expect(container.querySelectorAll(".layout-selection-group")).toHaveLength(1);
    expect(container.querySelectorAll(".layout-block.source-active")).toHaveLength(2);
    expect(container.querySelector(`[data-source-anchor="${paragraph}"]`)).toHaveAttribute("data-selected-chunk-ids", "chunk-1");
    expect(container.querySelector(`[data-source-anchor="${list}"]`)).toHaveAttribute("data-selected-chunk-ids", "chunk-1");

    fireEvent.click(screen.getByText("One"));
    expect(onSelect).toHaveBeenCalledWith(list);
  });

  it("uses one page-local enclosure per crossed page with the same Chunk identity", () => {
    const crossPage: DocumentLayoutPage[] = [
      { page_number: 1, blocks: [{ id: "part-1", type: "paragraph", source_anchor: "shared", text: "First", items: [], rows: [] }] },
      { page_number: 2, blocks: [{ id: "part-2", type: "paragraph", source_anchor: "shared", text: "Second", items: [], rows: [] }] },
    ];
    const groups = [{ id: "chunk-cross-page", sourceAnchors: ["shared"], sourceMappings: [] }];
    const { container } = render(
      <DocumentLayoutViewer
        formatPageLabel={(page) => `Page ${page}`}
        onKeyDown={vi.fn()}
        onSelect={vi.fn()}
        pages={crossPage}
        selectedAnchors={new Set(["shared"])}
        selectionGroups={groups}
      />,
    );
    const enclosures = Array.from(container.querySelectorAll('.layout-selection-group[data-chunk-id="chunk-cross-page"]'));
    expect(enclosures).toHaveLength(2);
    expect(enclosures.map((element) => element.getAttribute("data-page-number"))).toEqual(["1", "2"]);
  });

  it("does not enclose an unrelated block between non-contiguous anchors", () => {
    const nonContiguous: DocumentLayoutPage[] = [{
      page_number: 1,
      blocks: [
        { id: "a", type: "paragraph", source_anchor: "a", text: "A", items: [], rows: [] },
        { id: "unrelated", type: "paragraph", source_anchor: "unrelated", text: "Unrelated", items: [], rows: [] },
        { id: "c", type: "paragraph", source_anchor: "c", text: "C", items: [], rows: [] },
      ],
    }];
    const groups = [{ id: "chunk-safe", sourceAnchors: ["a", "c"], sourceMappings: [] }];
    const { container } = render(
      <DocumentLayoutViewer
        formatPageLabel={(page) => `Page ${page}`}
        onKeyDown={vi.fn()}
        onSelect={vi.fn()}
        pages={nonContiguous}
        selectedAnchors={new Set(["a", "c"])}
        selectionGroups={groups}
      />,
    );
    const enclosures = Array.from(container.querySelectorAll('.layout-selection-group[data-chunk-id="chunk-safe"]')) as HTMLElement[];
    expect(enclosures).toHaveLength(2);
    expect(enclosures.map((element) => element.style.gridRow)).toEqual(["1 / 2", "3 / 4"]);
    expect(container.querySelector('[data-source-anchor="unrelated"]')).not.toHaveAttribute("data-selected-chunk-ids");
  });

  it("renders one exact-range Markdown enclosure instead of per-line selection boxes", () => {
    const source = "Head\nIntro\n\n1. One\n2. Two\nTail";
    const onSelect = vi.fn();
    const mapped: MarkdownMappedChunk[] = [{
      id: "chunk-markdown",
      sourceMappings: [{ sourceAnchor: paragraph, markdownStart: 5, markdownEnd: 26, anchorStart: 0, anchorEnd: 5 }],
    }];
    const { container } = render(
      <CanonicalMarkdownSource
        chunks={mapped}
        onSelectChunkIds={onSelect}
        selectedChunkIds={["chunk-markdown"]}
        source={source}
      />,
    );
    const enclosure = container.querySelector('.canonical-markdown-selection-group[data-chunk-id="chunk-markdown"]');
    expect(enclosure).not.toBeNull();
    expect(enclosure).toHaveAttribute("data-markdown-start", "5");
    expect(enclosure).toHaveAttribute("data-markdown-end", "26");
    expect(container.querySelectorAll(".canonical-markdown-selection-group")).toHaveLength(1);
    expect(container.querySelector(".canonical-markdown-source")?.textContent).toBe(source);
    expect(container.querySelectorAll(".canonical-markdown-range.source-active")).toHaveLength(1);
    fireEvent.keyDown(screen.getByRole("button", { name: /Intro/ }), { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith(["chunk-markdown"]);
  });

  it("keeps different selected Chunks as different Markdown enclosures", () => {
    const source = "Alpha Beta Gamma";
    const mapped: MarkdownMappedChunk[] = [
      { id: "alpha", sourceMappings: [{ sourceAnchor: "a", markdownStart: 0, markdownEnd: 5, anchorStart: 0, anchorEnd: 5 }] },
      { id: "gamma", sourceMappings: [{ sourceAnchor: "g", markdownStart: 11, markdownEnd: 16, anchorStart: 0, anchorEnd: 5 }] },
    ];
    const { container } = render(<CanonicalMarkdownSource chunks={mapped} selectedChunkIds={["alpha", "gamma"]} source={source} />);
    expect(Array.from(container.querySelectorAll(".canonical-markdown-selection-group")).map((element) => element.getAttribute("data-chunk-id"))).toEqual(["alpha", "gamma"]);
  });

  it("positions the Markdown enclosure from the multiline range union without changing text", async () => {
    const source = "Before\nSelected line one\nSelected line two\nAfter";
    const mapped: MarkdownMappedChunk[] = [{
      id: "measured",
      sourceMappings: [{ sourceAnchor: "selected", markdownStart: 7, markdownEnd: 43, anchorStart: 0, anchorEnd: 36 }],
    }];
    const rect = (left: number, top: number, width: number, height: number): DOMRect => ({
      x: left,
      y: top,
      left,
      top,
      width,
      height,
      right: left + width,
      bottom: top + height,
      toJSON: () => ({}),
    });
    const geometry = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function () {
      if (this.classList.contains("canonical-markdown-source")) return rect(10, 20, 500, 300);
      if (this.classList.contains("canonical-markdown-range")) return rect(38, 74, 320, 96);
      return rect(0, 0, 0, 0);
    });
    const { container } = render(<CanonicalMarkdownSource chunks={mapped} selectedChunkIds={["measured"]} source={source} />);
    const enclosure = container.querySelector<HTMLElement>('.canonical-markdown-selection-group[data-chunk-id="measured"]');
    await waitFor(() => expect(enclosure).toHaveClass("is-positioned"));
    expect(enclosure?.style.left).toBe("28px");
    expect(enclosure?.style.top).toBe("54px");
    expect(enclosure?.style.width).toBe("320px");
    expect(enclosure?.style.height).toBe("96px");
    expect(container.querySelector(".canonical-markdown-source")?.textContent).toBe(source);
    geometry.mockRestore();
  });
});
