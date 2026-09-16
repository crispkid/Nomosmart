// Explicit component inputs, not a replacement API or generated/OCR document.
// This test entry is served only by the isolated browser runner, never Next routes.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { CanonicalMarkdownSource } from "@/components/CanonicalMarkdownSource";
import { DocumentLayoutViewer } from "@/components/DocumentLayoutViewer";
import type { DocumentLayoutBlock, DocumentLayoutPage } from "@/lib/api";
import type { MarkdownMappedChunk } from "@/lib/markdownSourceMapping";
import "@/app/globals.css";

const selectedText = Array.from({ length: 12 }, (_, index) =>
  `${index + 1}. **保留 Markdown 結構**；監控 \`vllm:num_requests_waiting\`，不改變原始內容。`).join("\n");
const source = `Before\n${selectedText}\nAfter`;
const start = 7;
const end = start + selectedText.length;
const mapped: MarkdownMappedChunk[] = [{ id: "measured", sourceMappings: [{
  sourceAnchor: "selected", markdownStart: start, markdownEnd: end,
  anchorStart: 0, anchorEnd: selectedText.length,
}] }];
const secondSource = "Alpha Beta Gamma";
const secondMapped: MarkdownMappedChunk[] = [
  { id: "alpha", sourceMappings: [{ sourceAnchor: "a", markdownStart: 0, markdownEnd: 5, anchorStart: 0, anchorEnd: 5 }] },
  { id: "gamma", sourceMappings: [{ sourceAnchor: "g", markdownStart: 11, markdownEnd: 16, anchorStart: 0, anchorEnd: 5 }] },
];
const base = { level: null, caption: null, confidence: null, bbox: null, items: [], rows: [] };
const paragraph: DocumentLayoutBlock = { ...base, id: "p", type: "paragraph", source_anchor: "p", text: "Introductory paragraph with preserved content." };
const list: DocumentLayoutBlock = { ...base, id: "l", type: "list", source_anchor: "l", text: null,
  items: ["**First** item", "**Second** item"], list_ordered: true, list_start: 1 };
const pages: DocumentLayoutPage[] = [{ page_number: 1, width: 794, height: 1123, blocks: [paragraph, list] }];
const splitPages: DocumentLayoutPage[] = [
  { ...pages[0], blocks: [{ ...paragraph, source_anchor: "shared" }] },
  { ...pages[0], page_number: 2, blocks: [{ ...paragraph, id: "p2", source_anchor: "shared", text: "Continuation" }] },
];
const separated: DocumentLayoutPage[] = [{ ...pages[0], blocks: [paragraph,
  { ...paragraph, id: "unrelated", source_anchor: "unrelated", text: "Unrelated block" }, list] }];

function Case() {
  const [lastSelection, setLastSelection] = useState("");
  const callbacks = { onSelect: setLastSelection,
    onKeyDown: (event: React.KeyboardEvent<HTMLElement>, anchor: string) => {
      if (event.key === "Enter") setLastSelection(anchor);
    }, formatPageLabel: (page: number) => `Page ${page}` };
  return <main style={{ padding: 12 }}>
    <p>Explicit isolated component inputs; actual production renderers and CSS.</p>
    <output id="selection-event">{lastSelection}</output>
    <section id="markdown-case" style={{ height: 280, overflow: "auto", width: "100%", maxWidth: 700 }}>
      <CanonicalMarkdownSource source={source} chunks={mapped} selectedChunkIds={["measured"]}
        onSelectChunkIds={(ids) => setLastSelection(ids.join(","))} />
    </section>
    <section id="different-case" style={{ maxWidth: 700 }}>
      <CanonicalMarkdownSource source={secondSource} chunks={secondMapped} selectedChunkIds={["alpha", "gamma"]} />
    </section>
    <section id="original-case" style={{ maxWidth: 800 }}>
      <DocumentLayoutViewer pages={pages} selectedAnchors={new Set(["p", "l"])}
        selectionGroups={[{ id: "original", sourceAnchors: ["p", "l"], sourceMappings: [] }]} {...callbacks} />
    </section>
    <section id="cross-page-case" style={{ maxWidth: 800 }}>
      <DocumentLayoutViewer pages={splitPages} selectedAnchors={new Set(["shared"])}
        selectionGroups={[{ id: "cross", sourceAnchors: ["shared"], sourceMappings: [] }]} {...callbacks} />
    </section>
    <section id="noncontiguous-case" style={{ maxWidth: 800 }}>
      <DocumentLayoutViewer pages={separated} selectedAnchors={new Set(["p", "l"])}
        selectionGroups={[{ id: "separated", sourceAnchors: ["p", "l"], sourceMappings: [] }]} {...callbacks} />
    </section>
  </main>;
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing isolated test root");
createRoot(root).render(<Case />);
