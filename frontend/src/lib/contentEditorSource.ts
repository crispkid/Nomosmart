import type { JSONContent } from "@tiptap/core";
import type { MarkdownManager } from "@tiptap/markdown";

type SourceBlock = { raw: string; prefix: string; signature: string; start: number; end: number };
export type SourceDocument = { source: string; blocks: Map<string, SourceBlock>; trailing: string; json: JSONContent };

function semantic(value: JSONContent): unknown {
  const attrs = Object.fromEntries(Object.entries(value.attrs ?? {}).filter(([key, item]) =>
    !["contentSourceId", "target", "rel", "class", "colwidth"].includes(key) && item !== null && item !== undefined && item !== false &&
    !(["start", "colspan", "rowspan"].includes(key) && item === 1)));
  return { type: value.type, ...(value.text !== undefined ? { text: value.text } : {}),
    ...(Object.keys(attrs).length ? { attrs } : {}),
    ...(value.marks?.length ? { marks: value.marks.map(semantic) } : {}),
    ...(value.content?.length ? { content: value.content.map(semantic) } : {}) };
}
function signature(node: JSONContent) { return JSON.stringify(semantic(node)); }
function singleBlock(raw: string, manager: MarkdownManager): JSONContent | null {
  const nodes = [...(manager.parse(raw).content ?? [])];
  // MarkdownManager emits empty trailing paragraphs for separator newlines.
  // Separators stay in the exact raw source; they are not a second block.
  while (nodes.length > 1 && nodes.at(-1)?.type === "paragraph" && !nodes.at(-1)?.content?.length) nodes.pop();
  return nodes.length === 1 ? nodes[0] : null;
}

export function sourceDocument(source: string, manager: MarkdownManager): SourceDocument | null {
  // These structures require the lossless text mode. Never silently import
  // them through a rich schema which cannot represent their full source.
  if (/<!--|<\/?[a-z][^>]*>|\[\^|^\s*\[[^\]]+\]:|!\[|^\s*[-*+]\s+\[[ xX]\]|(?:javascript|data|vbscript):/im.test(source)) return null;
  const tokens = manager.instance.lexer(source);
  const blocks = new Map<string, SourceBlock>();
  const content: JSONContent[] = [];
  let cursor = 0, prefix = "";
  for (const token of tokens) {
    if (source.slice(cursor, cursor + token.raw.length) !== token.raw) return null;
    const start = cursor;
    cursor += token.raw.length;
    if (token.type === "space") { prefix += token.raw; continue; }
    if (!["heading", "paragraph", "list", "blockquote", "table", "code", "hr"].includes(token.type)) return null;
    const node = singleBlock(token.raw, manager);
    if (!node) return null;
    const id = `source-${content.length}`;
    blocks.set(id, { raw: token.raw, prefix, signature: signature(node), start, end: cursor });
    content.push({ ...node, attrs: { ...node.attrs, contentSourceId: id } });
    prefix = "";
  }
  if (cursor !== source.length) return null;
  return { source, blocks, trailing: prefix, json: { type: "doc", content: content.length ? content : [{ type: "paragraph" }] } };
}

export function preserveSource(document: SourceDocument, json: JSONContent, manager: MarkdownManager): string {
  const content = json.content ?? [];
  const counts = new Map<string, number>();
  for (const node of content) {
    const id = node.attrs?.contentSourceId as string | undefined;
    if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  const used = new Set<string>();
  let result = "";
  for (const node of content) {
    const id = node.attrs?.contentSourceId as string | undefined;
    const original = id ? document.blocks.get(id) : undefined;
    const prefix = original && !used.has(id!) ? original.prefix : result ? "\n\n" : "";
    if (original && counts.get(id!) === 1 && signature(node) === original.signature) {
      result += prefix + original.raw;
    } else {
      const serialized = manager.serialize({ type: "doc", content: [node] });
      const readback = singleBlock(serialized, manager);
      if (serialized && (!readback || signature(readback) !== signature(node))) {
        throw new Error("content_edit_rich_roundtrip_unsupported");
      }
      const suffix = original?.raw.match(/\n*$/)?.[0] ?? "";
      result += prefix + serialized.replace(/\n+$/, "") + suffix;
    }
    if (id) used.add(id);
  }
  return result + document.trailing;
}

export function utf16Offset(text: string, codePointOffset: number) {
  let points = 0, offset = 0;
  for (const character of text) {
    if (points >= codePointOffset) break;
    offset += character.length; points += 1;
  }
  return offset;
}
