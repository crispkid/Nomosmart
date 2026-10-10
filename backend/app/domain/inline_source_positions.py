"""CommonMark token provenance for already-paginated visible text.

The existing parser owns grammar. Unknown projections fail exact round-trip.
"""
import re
from markdown_it import MarkdownIt
from markdown_it.rules_inline.state_inline import StateInline


class _PositionState(StateInline):
    @property
    def pending(self):
        return getattr(self, "_pending", "")

    @pending.setter
    def pending(self, value):
        old = getattr(self, "_pending", "")
        positions = getattr(self, "_pending_positions", [])
        if value.startswith(old):
            extra = value[len(old):]
            start = getattr(self, "pos", 0)
            exact = getattr(self, "src", "")[start:start + len(extra)] == extra
            positions = [*positions, *[(start + i, start + i + 1) if exact else None for i in range(len(extra))]]
        elif old.startswith(value):
            positions = positions[:len(value)]
        else:
            positions = [None] * len(value)
        self._pending, self._pending_positions = value, positions

    def pushPending(self):
        positions = list(self._pending_positions)
        token = super().pushPending()
        token.meta["source_positions"] = positions
        return token

    def push(self, ttype, tag, nesting):
        start = self.pos
        token = super().push(ttype, tag, nesting)
        token.meta["source_start"] = start
        return token


def inline_positions(raw: str, expected: str):
    md = MarkdownIt("commonmark", {"html": True, "linkify": False}).enable(["strikethrough"])
    state = _PositionState(raw, md, {}, [])
    md.inline.tokenize(state)
    # Emphasis balancing preserves tokens; text joining would discard their
    # individual positions, so extract before that final optimization.
    for rule in md.inline.ruler2.getRules(""):
        if rule.__name__ != "fragments_join":
            rule(state)
    glyphs = []
    for token in state.tokens:
        if token.type in {"text", "text_special"}:
            value = token.content
            positions = token.meta.get("source_positions")
            start = token.meta.get("source_start")
            if positions is None and isinstance(start, int):
                if token.type == "text_special":
                    positions = [(start, start + len(token.markup))] * len(value)
                elif raw[start:start + len(value)] == value:
                    positions = [(start + i, start + i + 1) for i in range(len(value))]
            if value and (positions is None or len(positions) != len(value) or any(p is None for p in positions)):
                return None
            glyphs.extend((ch, *position) for ch, position in zip(value, positions or []))
        elif token.type == "code_inline":
            start = token.meta.get("source_start")
            if not isinstance(start, int):
                return None
            start += len(token.markup)
            candidates = [start, start + 1]
            candidates = [p for p in candidates if raw[p:p + len(token.content)].replace("\n", " ") == token.content]
            if len(candidates) != 1:
                return None
            glyphs.extend((ch, candidates[0] + i, candidates[0] + i + 1) for i, ch in enumerate(token.content))
        elif token.type in {"softbreak", "hardbreak"}:
            start = token.meta.get("source_start")
            if not isinstance(start, int):
                return None
            glyphs.append(("\n", start, start + (2 if raw[start:start + 2] == "\\\n" else 1)))
        elif token.type == "html_inline":
            if re.sub(r"<[^>]*>", "", token.content):
                return None
        elif token.type == "image":
            return None
    normalized = []
    lines = [[]]
    breaks = []
    for glyph in glyphs:
        if glyph[0] == "\n":
            lines.append([])
            breaks.append(glyph)
        else:
            line = lines[-1]
            if glyph[0] in " \t":
                if line and line[-1][0] == " ":
                    line[-1] = (" ", line[-1][1], glyph[2])
                else:
                    line.append((" ", glyph[1], glyph[2]))
            else:
                line.append(glyph)
    for i, line in enumerate(lines):
        while line and line[0][0].isspace():
            line.pop(0)
        while line and line[-1][0].isspace():
            line.pop()
        normalized.extend(line)
        if i < len(breaks):
            normalized.append(breaks[i])
    while normalized and normalized[0][0].isspace():
        normalized.pop(0)
    while normalized and normalized[-1][0].isspace():
        normalized.pop()
    return normalized if "".join(g[0] for g in normalized) == expected else None
