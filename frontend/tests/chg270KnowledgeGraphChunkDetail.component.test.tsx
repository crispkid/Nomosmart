import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GraphExplorer, type GraphExplorerNode } from "@/components/GraphExplorer";
import { setLocalePreference } from "@/lib/i18nClient";

describe("CHG-270 graph Chunk inspector", () => {
  it("renders canonical number and the authorized Markdown display safely in both locales", async () => {
    setLocalePreference("en", false);
    const content = "Line one";
    const nodes: GraphExplorerNode[] = [{
      chunkContent: content,
      chunkDisplayMarkdown: "**Line one** with `inline-code`\n\n<script>alert('unsafe')</script>",
      chunkIndex: 7,
      contentType: "text",
      id: "chunk-7",
      kind: "chunk",
      title: "Line one script preview",
      x: 400,
      y: 300,
    }];
    const { container } = render(<GraphExplorer edges={[]} nodes={nodes} scopeLabel="Document v1" title="Knowledge graph" />);

    fireEvent.click(screen.getByRole("button", { name: "Chunk: Line one script preview" }));
    expect(screen.getByText("Number")).toBeInTheDocument();
    expect(screen.getByText("#7")).toHaveAttribute("data-graph-chunk-number", "true");
    const region = screen.getByRole("region", { name: "Full content" });
    expect(region.querySelector("strong")).toHaveTextContent("Line one");
    expect(region.querySelector("code.safe-markdown-semantic-code")).toHaveTextContent("inline-code");
    expect(container.querySelector("script")).toBeNull();

    act(() => setLocalePreference("zh", false));
    expect(screen.getByText("編號")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "完整內容" }).querySelector("strong")).toHaveTextContent("Line one");
    act(() => setLocalePreference("zh", false));
  });
});
