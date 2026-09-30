"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";


type CitationOptions = {
  citationCount?: number;
  citationLabel?: (ordinal: number) => string;
  citationMismatchLabel?: (ordinal: number) => string;
  onCitationSelect?: (ordinal: number) => void;
};

type MarkdownAstNode = {
  type?: string;
  value?: string;
  alt?: string;
  ordered?: boolean;
  start?: number | null;
  position?: { start?: { offset?: number }; end?: { offset?: number } };
  data?: { hName?: string; hProperties?: Record<string, unknown> };
  children?: MarkdownAstNode[];
};

const SKIP_CITATION_NODE_TYPES = new Set(["code", "inlineCode", "html", "link", "image", "definition"]);
const SAFE_ABSOLUTE_SCHEMES = new Set(["http:", "https:", "mailto:"]);

function remarkNomoSmart(source: string, citations = true) {
  return function plugin() {
    return function transform(tree: MarkdownAstNode) {
      transformAst(tree, source, [], citations);
    };
  };
}

/** Exact leaf positions are opt-in for the source viewer, never guessed by text search. */
function remarkSourcePositions(source: string, base: number) {
  return () => (tree: MarkdownAstNode) => {
    const points = (offset: number) => base + Array.from(source.slice(0, offset)).length;
    const bounds = new WeakMap<MarkdownAstNode, { start: number; end: number; direct: boolean }>();
    const envelopes = new WeakMap<MarkdownAstNode, { start: number; end: number; visibleStart: number; visibleEnd: number }>();
    function locate(node: MarkdownAstNode): { start: number; end: number } | undefined {
      const start = node.position?.start?.offset, end = node.position?.end?.offset;
      if (["text", "inlineCode", "code", "image"].includes(node.type ?? "") && typeof start === "number" && typeof end === "number") {
        let rawStart = start, rawEnd = end;
        if (node.type === "inlineCode") {
          const fence = /^`+/.exec(source.slice(start, end))?.[0].length ?? 0;
          if (source.slice(start + fence, end - fence) === node.value) { rawStart += fence; rawEnd -= fence; }
        }
        const range = { start: points(rawStart), end: points(rawEnd),
          direct: node.type !== "code" && node.type !== "image" && source.slice(rawStart, rawEnd) === node.value };
        bounds.set(node, range);
        envelopes.set(node, { start: points(start), end: points(end), visibleStart: range.start, visibleEnd: range.end });
        return range;
      }
      const descendants = (node.children ?? []).map(locate).filter((item) => item !== undefined);
      if (!descendants.length) return undefined;
      const visible = { start: descendants[0].start, end: descendants[descendants.length - 1].end };
      if (node.type !== "root" && typeof start === "number" && typeof end === "number") {
        envelopes.set(node, { start: points(start), end: points(end), visibleStart: visible.start, visibleEnd: visible.end });
      }
      return visible;
    }
    locate(tree);
    function visit(node: MarkdownAstNode, ancestors: MarkdownAstNode[] = []) {
      node.children = node.children?.map((child) => {
        const range = bounds.get(child);
        if (range) {
          return {
            type: "nomosmartSourceLeaf",
            data: { hName: "span", hProperties: {
              "data-source-start": range.start,
              "data-source-end": range.end,
              "data-source-direct": range.direct ? "true" : "false",
              "data-source-envelopes": JSON.stringify([...ancestors, node, child].map((item) => envelopes.get(item)).filter(Boolean)),
            } },
            children: [child],
          };
        }
        visit(child, [...ancestors, node]);
        return child;
      });
    }
    visit(tree);
  };
}

function transformAst(node: MarkdownAstNode, source: string, ancestors: string[], citations = true) {
  const type = node.type ?? "";
  if (type === "list" && node.ordered && node.children) {
    let expected = typeof node.start === "number" ? node.start : 1;
    for (const item of node.children) {
      const offset = item.position?.start?.offset;
      const marker = typeof offset === "number" ? /^\s{0,3}(\d+)[.)]\s+/.exec(source.slice(offset)) : null;
      const ordinal = marker ? Number(marker[1]) : expected;
      if (Number.isSafeInteger(ordinal) && ordinal > 0 && ordinal !== expected) {
        item.data = {
          ...item.data,
          hProperties: { ...(item.data?.hProperties ?? {}), value: ordinal },
        };
      }
      expected = Number.isSafeInteger(ordinal) && ordinal > 0 ? ordinal + 1 : expected + 1;
    }
  }
  if (!node.children?.length) return;
  const skipCitation = ancestors.some((ancestor) => SKIP_CITATION_NODE_TYPES.has(ancestor)) || SKIP_CITATION_NODE_TYPES.has(type);
  const nextChildren: MarkdownAstNode[] = [];
  for (const child of node.children) {
    if (citations && !skipCitation && child.type === "text" && typeof child.value === "string") {
      nextChildren.push(...citationNodes(child.value));
      continue;
    }
    transformAst(child, source, [...ancestors, type], citations);
    nextChildren.push(child);
  }
  node.children = nextChildren;
}

function citationNodes(value: string): MarkdownAstNode[] {
  const nodes: MarkdownAstNode[] = [];
  const pattern = /\[(\d+)\]/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(value)) !== null) {
    if (match.index > cursor) nodes.push({ type: "text", value: value.slice(cursor, match.index) });
    nodes.push({
      type: "nomosmartCitation",
      data: {
        hName: "span",
        hProperties: { "data-citation-ordinal": match[1] },
      },
      children: [{ type: "text", value: `[${match[1]}]` }],
    });
    cursor = match.index + match[0].length;
  }
  if (cursor < value.length) nodes.push({ type: "text", value: value.slice(cursor) });
  return nodes.length ? nodes : [{ type: "text", value }];
}

function safeUrlTransform(url: string) {
  const value = url.trim();
  if (!value || /[\u0000-\u001F\u007F]/.test(value) || value.startsWith("//")) return "";
  if (value.startsWith("#")) return value;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  try {
    const parsed = new URL(value);
    return SAFE_ABSOLUTE_SCHEMES.has(parsed.protocol) ? value : "";
  } catch {
    return "";
  }
}

function citationComponent(options: CitationOptions): Components["span"] {
  return function MarkdownSpan({ children, ...props }) {
    const ordinalValue = (props as Record<string, unknown>)["data-citation-ordinal"];
    const ordinal = typeof ordinalValue === "string" || typeof ordinalValue === "number" ? Number(ordinalValue) : Number.NaN;
    if (!Number.isInteger(ordinal) || ordinal < 1) return <span {...props}>{children}</span>;
    const interactive = Boolean(options.onCitationSelect) && ordinal <= (options.citationCount ?? 0);
    if (interactive) {
      return (
        <button
          aria-label={options.citationLabel?.(ordinal)}
          className="safe-markdown-citation safe-markdown-citation-button"
          onClick={() => options.onCitationSelect?.(ordinal)}
          type="button"
        >{children}</button>
      );
    }
    const mismatch = Boolean(options.onCitationSelect);
    return (
      <span
        aria-label={mismatch ? options.citationMismatchLabel?.(ordinal) : undefined}
        className={`safe-markdown-citation${mismatch ? " invalid" : ""}`}
        title={mismatch ? options.citationMismatchLabel?.(ordinal) : undefined}
      >{children}</span>
    );
  };
}

function markdownComponents(options: CitationOptions, inline: boolean): Components {
  return {
    p: ({ children }) => inline ? <>{children}</> : <p>{children}</p>,
    span: citationComponent(options),
    a: ({ href, children, ...props }) => {
      const safeHref = typeof href === "string" ? safeUrlTransform(href) : "";
      if (!safeHref) return <span className="safe-markdown-unsafe-link">{children}</span>;
      const external = /^https?:/i.test(safeHref);
      return <a {...props} href={safeHref} rel={external ? "noopener noreferrer" : undefined} target={external ? "_blank" : undefined}>{children}</a>;
    },
    img: ({ alt, title }) => {
      const label = alt || title || "Image";
      return <span aria-label={label} className="safe-markdown-image-placeholder" role="img">{label}</span>;
    },
    code: ({ children, className, ...props }) => (
      <code {...props} className={["safe-markdown-semantic-code", className].filter(Boolean).join(" ")}>{children}</code>
    ),
    strong: ({ children, className, ...props }) => (
      <strong {...props} className={["safe-markdown-semantic-strong", className].filter(Boolean).join(" ")}>{children}</strong>
    ),
    pre: ({ children, ...props }) => <pre {...props} className="safe-markdown-code-block">{children}</pre>,
    table: ({ children, ...props }) => <div className="safe-markdown-table-wrapper"><table {...props} className="safe-markdown-table">{children}</table></div>,
    input: (props) => <input {...props} disabled aria-disabled="true" />,
    ol: ({ children, className, ...props }) => <ol {...props} className={["safe-markdown-semantic-list", className].filter(Boolean).join(" ")}>{children}</ol>,
    ul: ({ children, className, ...props }) => <ul {...props} className={["safe-markdown-semantic-list", className].filter(Boolean).join(" ")}>{children}</ul>,
    li: ({ children, className, ...props }) => <li {...props} className={["safe-markdown-semantic-list-item", className].filter(Boolean).join(" ")}>{children}</li>,
    blockquote: ({ children, ...props }) => <blockquote {...props}>{children}</blockquote>,
  };
}

function MarkdownBody({ source, sourceOffset, inline = false, ...citationOptions }: { source: string; sourceOffset?: number; inline?: boolean } & CitationOptions) {
  const components = markdownComponents(citationOptions, inline);
  return (
    <ReactMarkdown
      components={components}
      remarkPlugins={sourceOffset === undefined ? [remarkGfm, remarkNomoSmart(source)] : [remarkGfm, remarkNomoSmart(source, false), remarkSourcePositions(source, sourceOffset)]}
      skipHtml
      urlTransform={safeUrlTransform}
    >{source}</ReactMarkdown>
  );
}

export function SafeMarkdownInline({ source }: { source: string }) {
  return <MarkdownBody inline source={source} />;
}

export function SafeMarkdown({
  citationCount,
  citationLabel,
  citationMismatchLabel,
  className = "",
  onCitationSelect,
  source,
  sourceOffset,
}: { className?: string; source: string; sourceOffset?: number } & CitationOptions) {
  const classes = ["safe-markdown", className].filter(Boolean).join(" ");
  return (
    <div className={classes}>
      <MarkdownBody
        citationCount={citationCount}
        citationLabel={citationLabel}
        citationMismatchLabel={citationMismatchLabel}
        onCitationSelect={onCitationSelect}
        source={source}
        sourceOffset={sourceOffset}
      />
    </div>
  );
}
