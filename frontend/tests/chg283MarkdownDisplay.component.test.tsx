import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChunkMarkdownView, selectChunkMarkdownSource, type ChunkMarkdownSource } from "@/components/ChunkMarkdownView";
import { ChatResponseEvidence } from "@/components/ChatResponseEvidence";
import { GraphExplorer, type GraphExplorerNode } from "@/components/GraphExplorer";
import { SafeMarkdownInline } from "@/components/SafeMarkdown";
import { setLocalePreference } from "@/lib/i18nClient";
import type { ProjectChatCitation } from "@/lib/api";

const vllmMarkdown = [
  "1. **vLLM 擴容策略：** 監控 `vllm:num_requests_waiting`。為避免模型冷啟動造成服務中斷，最小副本數嚴格設定為 `minReplica: 1`。",
  "2. **Triton 擴容策略：** 監控佇列等待時間。因小模型拉取極快，允許設定 Scale to Zero 以釋放 GPU 資源。",
].join("\n");

describe("CHG-283 Chunk Markdown source contract", () => {
  it("selects complete display Markdown before raw Markdown and display text, never retrieval text", () => {
    const source = {
      content: "DISPLAY TEXT",
      display_markdown: "**DISPLAY MARKDOWN**",
      markdown_content: "**RAW MARKDOWN**",
      retrieval_text: "RETRIEVAL-ONLY SENTINEL",
    } as ChunkMarkdownSource & { retrieval_text: string };

    expect(selectChunkMarkdownSource(source)).toEqual({ kind: "display_markdown", source: "**DISPLAY MARKDOWN**" });
    expect(selectChunkMarkdownSource({ ...source, display_markdown: " \n " })).toEqual({ kind: "markdown_content", source: "**RAW MARKDOWN**" });
    expect(selectChunkMarkdownSource({ content: "DISPLAY TEXT", display_markdown: null, markdown_content: null })).toEqual({ kind: "content", source: "DISPLAY TEXT" });
    expect(selectChunkMarkdownSource({ display_markdown: null, markdown_content: null, content: null })).toBeNull();
  });

  it("faithfully renders the approved ordered-list, strong and inline-code semantics", () => {
    const { container } = render(
      <ChunkMarkdownView
        chunk={{
          content: "flattened fallback",
          display_markdown: vllmMarkdown,
          markdown_content: "raw fallback",
        }}
      />,
    );

    const items = container.querySelectorAll("ol > li");
    expect(items).toHaveLength(2);
    expect(items[0].querySelector("strong")).toHaveTextContent("vLLM 擴容策略：");
    expect(items[1].querySelector("strong")).toHaveTextContent("Triton 擴容策略：");
    expect(screen.getByText("vllm:num_requests_waiting")).toHaveClass("safe-markdown-semantic-code");
    expect(screen.getByText("minReplica: 1")).toHaveClass("safe-markdown-semantic-code");
    expect(container).not.toHaveTextContent("flattened fallback");
    expect(container).not.toHaveTextContent("raw fallback");
  });

  it("keeps split list, table and code projections local to their own Chunk", () => {
    const { container } = render(
      <>
        <ChunkMarkdownView className="list-unit" chunk={{ display_markdown: "3. Third\n4. Fourth" }} />
        <ChunkMarkdownView className="table-unit" chunk={{ display_markdown: "| Product | Rate |\n| --- | --- |\n| B | 2.3% |" }} />
        <ChunkMarkdownView className="code-unit" chunk={{ display_markdown: "```yaml\nminReplica: 1\n```" }} />
      </>,
    );

    expect(container.querySelector(".list-unit ol")).toHaveAttribute("start", "3");
    expect(container.querySelector(".list-unit")).toHaveTextContent("Third");
    expect(container.querySelector(".list-unit")).toHaveTextContent("Fourth");
    expect(container.querySelector(".table-unit table")).toHaveTextContent("ProductRateB2.3%");
    expect(container.querySelector(".table-unit")).not.toHaveTextContent("A2.1%");
    expect(container.querySelector(".code-unit pre code.language-yaml")).toHaveTextContent("minReplica: 1");
  });

  it("uses one semantic code class in inline and full Markdown renderers", () => {
    const { container } = render(
      <>
        <span data-testid="inline"><SafeMarkdownInline source={"`minReplica: 1`"} /></span>
        <ChunkMarkdownView chunk={{ display_markdown: "`minReplica: 1`" }} />
      </>,
    );
    const codes = container.querySelectorAll("code.safe-markdown-semantic-code");
    expect(codes).toHaveLength(2);
    expect(codes[0]).toHaveTextContent("minReplica: 1");
    expect(codes[1]).toHaveTextContent("minReplica: 1");
    expect(container).not.toHaveTextContent("`minReplica: 1`");
  });

  it("retains the CHG-282 hostile HTML and URL safety boundary", () => {
    const { container } = render(
      <ChunkMarkdownView chunk={{ display_markdown: "<script>alert('unsafe')</script>\n\n[bad](javascript:alert(1))\n\n![tracker](//tracker.example/pixel.png)" }} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("bad").closest("a")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("tracker")).toHaveClass("safe-markdown-image-placeholder");
  });
});

describe("CHG-283 full-detail surface integration", () => {
  it("keeps a compact Graph title but renders complete Markdown in the Chunk inspector", () => {
    setLocalePreference("en", false);
    const nodes: GraphExplorerNode[] = [{
      chunkContent: "Plain compact content",
      chunkDisplayMarkdown: vllmMarkdown,
      chunkIndex: 20,
      contentType: "text",
      id: "chunk-20",
      kind: "chunk",
      title: "Plain compact title",
      x: 400,
      y: 300,
    }];
    render(<GraphExplorer edges={[]} nodes={nodes} scopeLabel="Document v1" title="Knowledge graph" />);

    fireEvent.click(screen.getByRole("button", { name: "Chunk: Plain compact title" }));
    const region = screen.getByRole("region", { name: "Full content" });
    expect(within(region).getAllByRole("listitem")).toHaveLength(2);
    expect(within(region).getByText("vllm:num_requests_waiting")).toHaveClass("safe-markdown-semantic-code");
    expect(region).not.toHaveTextContent("Plain compact content");
  });

  it("keeps the citation card plain and renders only the complete authorized source in expanded detail", () => {
    setLocalePreference("en", false);
    const citation: ProjectChatCitation = {
      chunk_id: "11111111-1111-4111-8111-111111111111",
      chunk_index: 20,
      content: "Plain full fallback",
      content_type: "text",
      display_markdown: vllmMarkdown,
      document_id: "22222222-2222-4222-8222-222222222222",
      document_version_id: "33333333-3333-4333-8333-333333333333",
      excerpt: "Compact **truncated preview",
      index_name: "staging-index",
      page: 3,
      score: 0.95,
      title: "Document title",
    };
    render(
      <ChatResponseEvidence
        answer="Grounded response [1]"
        answerFallback="No answer"
        citations={[citation]}
        citationsLabel="Citations"
        idPrefix="chg283-chat"
        noCitationsLabel="No citations"
      />,
    );

    const card = screen.getByRole("button", { name: /Open source \[1\]/ });
    expect(card).toHaveTextContent("Compact **truncated prev…");
    expect(card.querySelector("strong")?.textContent).toBe("Compact **truncated prev…");
    fireEvent.click(screen.getByRole("button", { name: "View citation source [1]" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(2);
    expect(within(dialog).getByText("vllm:num_requests_waiting")).toHaveClass("safe-markdown-semantic-code");
    expect(dialog.querySelector(".chat-citation-markdown")).not.toHaveTextContent("Compact **truncated preview");
  });
});
