import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DocumentLayoutViewer } from "@/components/DocumentLayoutViewer";
import { SafeMarkdown, SafeMarkdownInline } from "@/components/SafeMarkdown";
import type { DocumentLayoutPage } from "@/lib/api";

const nullableLayoutFields = { text: null, level: null, caption: null, confidence: null, bbox: null };

describe("CHG-282 safe CommonMark/GFM rendering", () => {
  it("renders inline code without visible Markdown backticks", () => {
    render(<SafeMarkdownInline source={"監控 `vllm:num_requests_waiting` 並設定 `minReplica: 1`。"} />);
    expect(screen.getByText("vllm:num_requests_waiting").tagName).toBe("CODE");
    expect(screen.getByText("minReplica: 1").tagName).toBe("CODE");
    expect(document.body).not.toHaveTextContent("`vllm:num_requests_waiting`");
  });

  it("keeps fenced code literal and does not convert citations inside code", () => {
    const { container } = render(<SafeMarkdown citationCount={2} onCitationSelect={vi.fn()} source={"```yaml\nmetric: `[1]`\n```"} />);
    expect(container.querySelector("pre code")).toHaveTextContent("metric: `[1]`");
    expect(container.querySelector("pre .safe-markdown-citation")).toBeNull();
  });

  it("renders the approved GFM structures as semantic elements", () => {
    const source = [
      "# Heading",
      "",
      "> A note with *emphasis* and ~~removed~~ text.",
      "",
      "- [x] Complete",
      "- [ ] Pending",
      "",
      "| Key | Value |",
      "| --- | --- |",
      "| Mode | Live |",
      "",
      "[Safe link](https://example.com)",
      "",
      "---",
    ].join("\n");
    const { container } = render(<SafeMarkdown source={source} />);
    expect(screen.getByRole("heading", { name: "Heading" })).toBeInTheDocument();
    expect(container.querySelector("blockquote em")).toHaveTextContent("emphasis");
    expect(container.querySelector("blockquote del")).toHaveTextContent("removed");
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(2);
    expect(screen.getByRole("table")).toHaveTextContent("ModeLive");
    expect(screen.getByRole("link", { name: "Safe link" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(container.querySelector("hr")).toBeInTheDocument();
  });

  it("preserves explicit ordered item values and normal-text citations", () => {
    const onCitationSelect = vi.fn();
    const { container } = render(<SafeMarkdown citationCount={1} onCitationSelect={onCitationSelect} source={"1. First\n3. Third\n4. Fourth\n\nEvidence [1]"} />);
    const items = Array.from(container.querySelectorAll("ol > li"));
    expect(items.map((item) => item.getAttribute("value"))).toEqual([null, "3", null]);
    fireEvent.click(screen.getByRole("button", { name: /1/ }));
    expect(onCitationSelect).toHaveBeenCalledWith(1);
  });

  it("keeps raw HTML and unsafe resource URLs inert", () => {
    const source = '<script>window.pwned=1</script>\n\n[bad](javascript:alert(1))\n\n![tracker](//tracker.example/pixel.png)';
    const { container } = render(<SafeMarkdown source={source} />);
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("bad").closest("a")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("tracker")).toHaveClass("safe-markdown-image-placeholder");
  });

  it("applies the shared link, image and citation fallback policy", () => {
    const source = [
      "Unmapped [2]",
      "",
      "[Mail](mailto:ops@example.com) [Root](/docs) [Section](#part) [Protocol](//unsafe.example)",
      "",
      "![Local diagram](diagram.png)",
    ].join("\n");
    const { container } = render(
      <SafeMarkdown citationCount={1} citationMismatchLabel={(ordinal) => `Missing ${ordinal}`} onCitationSelect={vi.fn()} source={source} />,
    );
    expect(screen.getByText("[2]")).toHaveClass("invalid");
    expect(screen.getByText("[2]")).toHaveAttribute("title", "Missing 2");
    expect(screen.getByRole("link", { name: "Mail" })).toHaveAttribute("href", "mailto:ops@example.com");
    expect(screen.getByRole("link", { name: "Root" })).toHaveAttribute("href", "/docs");
    expect(screen.getByRole("link", { name: "Section" })).toHaveAttribute("href", "#part");
    expect(screen.getByText("Protocol").closest("a")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("Local diagram")).toHaveClass("safe-markdown-image-placeholder");
  });
});


describe("CHG-282 lossless document pages", () => {
  it("renders every additive layout block through the shared semantic viewer", () => {
    const onKeyDown = vi.fn();
    const pages: DocumentLayoutPage[] = [{
      page_number: 1,
      width: 794,
      height: 1123,
      blocks: [
        ...[1, 2, 3, 4, 5, 6].map((level) => ({ ...nullableLayoutFields, id: `h-${level}`, type: "heading" as const, source_anchor: `h-${level}`, text: `Heading ${level}`, level, items: [], rows: [] })),
        { ...nullableLayoutFields, id: "legacy-list", type: "list", source_anchor: "legacy-list", items: ["Legacy one", "Legacy two"], rows: [], list_ordered: true, list_start: 4 },
        { ...nullableLayoutFields, id: "table", type: "table", source_anchor: "table", items: [], table_header: ["Key", "Value"], rows: [["Mode", "Live"]] },
        { ...nullableLayoutFields, id: "image", type: "image", source_anchor: "image", items: [], rows: [], caption: "Architecture caption" },
        { ...nullableLayoutFields, id: "code", type: "code", source_anchor: "code", text: "metric: [1]", items: [], rows: [], code_language: "yaml" },
        { ...nullableLayoutFields, id: "quote", type: "blockquote", source_anchor: "quote", text: "Important note", items: [], rows: [] },
        { ...nullableLayoutFields, id: "rule", type: "horizontal_rule", source_anchor: "rule", items: [], rows: [] },
        { ...nullableLayoutFields, id: "paragraph", type: "paragraph", source_anchor: "paragraph", text: "Plain text", items: [], rows: [] },
      ],
    }];
    const { container } = render(<DocumentLayoutViewer formatPageLabel={(page) => `Page ${page}`} onKeyDown={onKeyDown} onSelect={vi.fn()} pages={pages} selectedAnchors={new Set()} />);

    for (let level = 1; level <= 6; level += 1) expect(screen.getByRole("heading", { level, name: `Heading ${level}` })).toBeInTheDocument();
    expect(container.querySelector("ol")).toHaveAttribute("start", "4");
    expect(screen.getByRole("table")).toHaveTextContent("KeyValueModeLive");
    expect(screen.getByText("Architecture caption").closest("figure")).toBeInTheDocument();
    expect(container.querySelector("pre code.language-yaml")).toHaveTextContent("metric: [1]");
    expect(container.querySelector("blockquote")).toHaveTextContent("Important note");
    expect(container.querySelector("hr")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByText("Plain text"), { key: "Enter" });
    expect(onKeyDown).toHaveBeenCalled();
  });

  it("renders nested list metadata without flattening its relationship", () => {
    const pages: DocumentLayoutPage[] = [{
      page_number: 1,
      width: 794,
      height: 1123,
      blocks: [{
        ...nullableLayoutFields,
        id: "list-1",
        type: "list",
        source_anchor: "list-1",
        items: ["Parent"],
        rows: [],
        list_ordered: true,
        list_start: 1,
        list_items: [{
          text: "Parent",
          value: 1,
          child_lists: [{ ordered: false, start: 1, items: [{ text: "Nested bullet", value: 1 }] }],
        }],
      }],
    }];
    const { container } = render(<DocumentLayoutViewer formatPageLabel={(page) => `Page ${page}`} onKeyDown={vi.fn()} onSelect={vi.fn()} pages={pages} selectedAnchors={new Set()} />);
    expect(container.querySelector("ol > li > .layout-nested-list > ul > li")).toHaveTextContent("Nested bullet");
  });

  it("shares one selected source anchor across continuation pages", () => {
    const pages: DocumentLayoutPage[] = [
      {
        page_number: 1,
        width: 794,
        height: 1123,
        blocks: [{ id: "p-1-c1", type: "paragraph", source_anchor: "p-1", text: "first", level: null, items: [], rows: [], caption: null, confidence: 1, bbox: null, continuation_of: "p-1", continuation_index: 1, continuation_count: 2 }],
      },
      {
        page_number: 2,
        width: 794,
        height: 1123,
        blocks: [{ id: "p-1-c2", type: "paragraph", source_anchor: "p-1", text: "second", level: null, items: [], rows: [], caption: null, confidence: 1, bbox: null, continuation_of: "p-1", continuation_index: 2, continuation_count: 2 }],
      },
    ];
    const onSelect = vi.fn();
    const { container } = render(<DocumentLayoutViewer formatPageLabel={(page) => `Page ${page}`} onKeyDown={vi.fn()} onSelect={onSelect} pages={pages} selectedAnchors={new Set(["p-1"])} />);
    expect(container.querySelectorAll('.layout-block.source-active[data-source-anchor="p-1"]')).toHaveLength(2);
    fireEvent.click(screen.getByText("second"));
    expect(onSelect).toHaveBeenCalledWith("p-1");
  });
});
