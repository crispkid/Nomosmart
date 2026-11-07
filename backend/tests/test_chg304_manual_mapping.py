"""Actual parser/manual factory regression; not Provider or HTTP acceptance."""
from hashlib import sha256
import unittest

from app.domain.markdown_artifacts import normalize_source_mappings, resolve_manual_source_mapping
from app.domain.markdown_structure import MarkdownStructureParser
from app.domain.chunk_representations import build_manual_chunk_representation


class ManualMappingTests(unittest.TestCase):
    source = "# 規範\n\n條件😀如下：\n\n1. **年滿18歲**\n2. 具有`身分證`\n\n條件😀如下：\n"

    def resolve(self, start, end, anchor="markdown-document", **kwargs):
        return resolve_manual_source_mapping(content=self.source[start:end], markdown=self.source,
            source_anchor=anchor, start_offset=start, end_offset=end,
            offset_scope=kwargs.get("scope", "canonical_markdown"), offset_unit="unicode_code_point")

    def test_cross_block_ast_identity_and_reload(self):
        structure = MarkdownStructureParser().parse(self.source)
        paragraph = next(node for node in structure.nodes if node.type == "paragraph")
        listing = next(node for node in structure.nodes if node.type == "list")
        mapping = self.resolve(paragraph.start_offset, listing.end_offset, paragraph.id)
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping["source_anchors"], [paragraph.id, listing.id])
        raw = self.source[paragraph.start_offset:listing.end_offset]
        representation = build_manual_chunk_representation(raw_markdown=raw, document_title="規範")
        self.assertEqual(representation.raw_markdown, raw)
        self.assertEqual(representation.display_markdown, raw)
        self.assertNotIn("**", representation.retrieval_text)
        reloaded = normalize_source_mappings(representation.display_text, [mapping], self.source)[0]
        self.assertEqual(reloaded["mapping_status"], "resolved")
        self.assertEqual(reloaded["markdown_fragment_sha256"], sha256(raw.encode()).hexdigest())

    def test_repeated_text_uses_supplied_exact_offset(self):
        start = self.source.rindex("條件")
        result = self.resolve(start, start + len("條件😀如下："))
        self.assertEqual(result["markdown_start_offset"], start)

    def test_wrong_anchor_and_stale_hash_are_not_repaired_by_guessing(self):
        start = self.source.rindex("條件")
        self.assertIsNone(self.resolve(start, start + 4, "node-forged"))
        mapping = self.resolve(start, start + 4)
        corrupted = {**mapping, "markdown_fragment_sha256": "0" * 64}
        self.assertEqual(normalize_source_mappings("條件😀如", [corrupted], self.source)[0]["mapping_status"], "unresolved")

    def test_invalid_ranges_and_units_rejected(self):
        for start, end, unit in [(-1, 3, "unicode_code_point"), (0, 10000, "unicode_code_point"), (3, 3, "unicode_code_point"), (0, 2, "utf16")]:
            self.assertIsNone(resolve_manual_source_mapping(content="# ", markdown=self.source, source_anchor="markdown-document",
                start_offset=start, end_offset=end, offset_scope="canonical_markdown", offset_unit=unit))

    def test_legacy_local_offsets_must_be_exact(self):
        raw = "abcdef"
        self.assertIsNone(resolve_manual_source_mapping(content="cde", markdown=raw, source_anchor="paragraph-1",
            start_offset=0, end_offset=3, offset_scope="source_anchor", offset_unit="unicode_code_point"))
        result = resolve_manual_source_mapping(content="cde", markdown=raw, source_anchor="paragraph-1",
            start_offset=2, end_offset=5, offset_scope="source_anchor", offset_unit="unicode_code_point")
        self.assertEqual(result["markdown_start_offset"], 2)


if __name__ == "__main__":
    unittest.main()
