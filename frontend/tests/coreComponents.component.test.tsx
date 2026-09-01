import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApprovalEvidenceViewer } from "@/components/ApprovalEvidenceViewer";
import { CanonicalMarkdownSource } from "@/components/CanonicalMarkdownSource";
import { GraphExplorer, type GraphExplorerEdge, type GraphExplorerNode } from "@/components/GraphExplorer";
import { PipelineList } from "@/components/PipelineList";
import { SafeMarkdown } from "@/components/SafeMarkdown";
import { setLocalePreference, useI18n } from "@/lib/i18nClient";
import { runtimeConfig } from "@/lib/runtimeConfig";


describe("rendered operational components", () => {
  it("keeps translation callbacks stable until the locale changes", () => {
    const renders: Array<ReturnType<typeof useI18n>> = [];
    function I18nProbe({ tick }: { tick: number }) {
      const i18n = useI18n();
      renders.push(i18n);
      return <span>{tick}:{i18n.t("systemUsers")}</span>;
    }

    setLocalePreference("zh", false);
    const { rerender } = render(<I18nProbe tick={1} />);
    const first = renders.at(-1)!;
    rerender(<I18nProbe tick={2} />);
    const second = renders.at(-1)!;

    expect(second.t).toBe(first.t);
    expect(second.format).toBe(first.format);
    expect(screen.getByText("2:使用者管理")).toBeInTheDocument();

    act(() => setLocalePreference("en", false));
    const english = renders.at(-1)!;
    expect(english.t).not.toBe(second.t);
    expect(english.format).not.toBe(second.format);
    expect(screen.getByText("2:Users")).toBeInTheDocument();
    act(() => setLocalePreference("zh", false));
  });

  it("renders structured markdown without treating markup as HTML", () => {
    render(<SafeMarkdown source={"# Evidence\n\n**Grounded** [1]\n\n| Key | Value |\n| --- | --- |\n| Mode | Live |\n\n- First\n- Second"} />);
    expect(screen.getByRole("heading", { name: "Evidence" })).toBeInTheDocument();
    expect(screen.getByText("Grounded").tagName).toBe("STRONG");
    expect(screen.getByRole("table")).toHaveTextContent("ModeLive");
    expect(screen.getByText("[1]")).toHaveClass("safe-markdown-citation");
  });

  it("preserves explicit ordered markers across intervening answer blocks", () => {
    const source = [
      "1. **Dual fabric**",
      "",
      "Traffic is separated. [1]",
      "",
      "2. **Business network**",
      "",
      "- External API",
      "- Kubernetes",
      "",
      "The management entry remains isolated. [2]",
      "",
      "3. **Compute network**",
    ].join("\n");

    const { container } = render(<SafeMarkdown source={source} />);
    const orderedLists = Array.from(container.querySelectorAll("ol"));
    expect(orderedLists).toHaveLength(3);
    expect(orderedLists.map((list) => list.getAttribute("start"))).toEqual([null, "2", "3"]);
    expect(orderedLists.map((list) => list.querySelector("li")?.textContent)).toEqual([
      "Dual fabric",
      "Business network",
      "Compute network",
    ]);
  });

  it("preserves jumps, intentional restarts and alternate ordered markers", () => {
    const { container } = render(
      <SafeMarkdown source={"1. First\n3. Third\n4. Fourth\n\nPeer paragraph\n\n1) Restart"} />,
    );
    const orderedLists = Array.from(container.querySelectorAll("ol"));
    expect(orderedLists).toHaveLength(2);
    expect(orderedLists[0]).not.toHaveAttribute("start");
    expect(Array.from(orderedLists[0].children).map((item) => item.getAttribute("value"))).toEqual([null, "3", null]);
    expect(orderedLists[1]).not.toHaveAttribute("start");
    expect(orderedLists[1]).toHaveTextContent("Restart");
  });

  it("keeps indented continuation content and nested lists inside the owning ordered item", async () => {
    const onCitationSelect = vi.fn();
    const user = userEvent.setup();
    const source = [
      "1. Parent",
      "   Continued evidence [2]",
      "   - Nested bullet",
      "     Nested detail",
      "   2. Nested ordered",
      "2. Next",
    ].join("\n");
    const { container } = render(
      <SafeMarkdown citationCount={2} onCitationSelect={onCitationSelect} source={source} />,
    );

    const topLevelList = container.querySelector(".safe-markdown > ol");
    expect(topLevelList?.children).toHaveLength(2);
    const firstItem = topLevelList?.children[0];
    expect(firstItem).toHaveTextContent("Parent Continued evidence [2] Nested bullet Nested detail Nested ordered");
    expect(firstItem?.querySelector("ul")).toBeInTheDocument();
    expect(firstItem?.querySelector("ol")).toHaveAttribute("start", "2");
    await user.click(screen.getByRole("button", { name: "[2]" }));
    expect(onCitationSelect).toHaveBeenCalledWith(2);
  });

  it("does not reinterpret citations, versions, dates, decimals or raw html as ordered lists", () => {
    const source = "Evidence [1] uses v1.2 on 2026.08.27 with value 1.5.\n\nA sentence contains 1. text without a line marker.\n\n<script>alert('no')</script>";
    const { container } = render(<SafeMarkdown source={source} />);
    expect(container.querySelector("ol")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("[1]")).toHaveClass("safe-markdown-citation");
    expect(container).not.toHaveTextContent("alert('no')");
  });

  it("renders canonical Markdown as exact inert source text", () => {
    const source = "# Heading\n\n<script>alert('no')</script>\n\n- item";
    const onSelect = vi.fn();
    const chunks = [{ id: "chunk-1", sourceMappings: [{ sourceAnchor: "paragraph-1", markdownStart: 0, markdownEnd: 9, anchorStart: 0, anchorEnd: 9 }] }];
    const { container } = render(<CanonicalMarkdownSource chunks={chunks} onSelectChunkIds={onSelect} selectedChunkIds={["chunk-1"]} source={source} />);
    expect(container.querySelector(".canonical-markdown-source")?.textContent).toBe(source);
    expect(container.querySelector("h1")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    const mapped = screen.getByRole("button", { name: "# Heading" });
    expect(mapped).toHaveAttribute("aria-current", "true");
    fireEvent.keyDown(mapped, { key: "Escape" });
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.keyDown(mapped, { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith(["chunk-1"]);
    fireEvent.click(mapped);
    expect(onSelect).toHaveBeenCalledTimes(2);
  });

  it("switches approval evidence views and binds source selection to chunks", async () => {
    const user = userEvent.setup();
    render(
      <ApprovalEvidenceViewer
        chunks={[{ id: "chunk-1", index: 1, type: "text", sourceAnchor: "paragraph-1", sourceMappings: [{ sourceAnchor: "paragraph-1", markdownStart: 0, markdownEnd: 16, anchorStart: 0, anchorEnd: 16 }], sourceLabel: "Page 1", content: "Evidence content", tags: ["policy"] }]}
        documentLayout={null}
        documentTitle="Policy"
        markdownText="Evidence content"
        originalFile={null}
        sourceText={null}
        version="v1"
      />,
    );
    await user.click(screen.getByRole("button", { name: /Markdown/i }));
    const source = screen.getByText("Evidence content", { selector: ".canonical-markdown-range" });
    expect(source).toHaveAttribute("data-source-anchor", "paragraph-1");
    await user.click(source!);
    expect(screen.getByRole("button", { name: /chunk-1/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("renders pipeline empty, progress and retry states in both locales", async () => {
    setLocalePreference("en", false);
    const { rerender } = render(<PipelineList />);
    expect(screen.getByText(/no live pipeline run data/i)).toBeInTheDocument();
    rerender(<PipelineList runs={[{ id: "run-1", document: "Policy", version: "v1", source: "upload", status: "failed", progress: 55, currentStep: "OCR", elapsed: "1m", eta: "-", steps: [["Upload", "completed"], ["OCR", "failed"]] }]} />);
    expect(screen.getByText("Policy")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry failed step/i })).toBeInTheDocument();
    setLocalePreference("zh", false);
  });

  it("supports graph node selection, semantic zoom and reset controls", async () => {
    setLocalePreference("en", false);
    const user = userEvent.setup();
    const nodes: GraphExplorerNode[] = [
      { id: "project-1", kind: "project", semanticLayer: 1, title: "Project", x: 300, y: 300 },
      { id: "document-1", kind: "document", semanticLayer: 2, title: "Document", x: 520, y: 300 },
      { id: "chunk-1", kind: "chunk", semanticLayer: 3, minZoom: 1.5, title: "Chunk", x: 700, y: 300 },
    ];
    const edges: GraphExplorerEdge[] = [{ id: "edge-1", source: "project-1", target: "document-1", relation: "contains", label: "contains" }];
    render(<GraphExplorer edges={edges} nodes={nodes} scopeLabel="Project scope" title="Knowledge graph" />);
    expect(screen.getByText("Project")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /zoom in/i }));
    await user.click(screen.getByRole("button", { name: /reset/i }));
    expect(screen.getByText("Project scope")).toBeInTheDocument();
    setLocalePreference("zh", false);
  });

  it("reads server-emitted runtime configuration", () => {
    window.__NOMOSMART_RUNTIME_CONFIG__ = { appOrigin: "https://app.example.test", apiBaseUrl: "/runtime-api", oidcIssuerUrl: "https://id.example.test/realms/nomosmart", oidcClientId: "frontend", oidcAudience: "backend" };
    expect(runtimeConfig().apiBaseUrl).toBe("/runtime-api");
    delete window.__NOMOSMART_RUNTIME_CONFIG__;
  });
});
