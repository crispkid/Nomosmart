"""Actual parser-independent source contracts; no service substitutes."""
from app.domain.content_diff import equal_source_ranges, rebase_range, text_digest


def test_unicode_range_shifts_without_utf16_confusion():
    old = "# 規定\n\n🙂對象\n\n末段\n"
    new = "# 規定\n\n新增內容\n\n🙂對象\n\n末段\n"
    start = old.index("🙂")
    mapped = rebase_range(equal_source_ranges(old,new),start,start+len("🙂對象"))
    assert mapped is not None and new[slice(*mapped)] == "🙂對象"
    assert mapped[0] == new.index("🙂")


def test_inserted_duplicate_is_not_first_text_lookup():
    old = "# 規定\n\n相同段落\n\n相同段落\n"
    new = "# 規定\n\n相同段落\n\n相同段落\n\n相同段落\n"
    start = old.index("相同段落")
    assert rebase_range(equal_source_ranges(old,new),start,start+len("相同段落")) is None


def test_edit_does_not_rebase_changed_manual_span():
    old,new = "前段\n\n原始內容\n\n後段\n","前段\n\n修正內容\n\n後段\n"
    start=old.index("原始內容")
    assert rebase_range(equal_source_ranges(old,new),start,start+4) is None
    tail=old.index("後段")
    assert rebase_range(equal_source_ranges(old,new),tail,tail+2) == (new.index("後段"),new.index("後段")+2)


def test_unchanged_repeated_content_has_exact_identity():
    source="重複\n"*1000
    assert rebase_range(equal_source_ranges(source,source),900,906) == (900,906)
    assert text_digest(source) == text_digest(source)


def test_empty_and_invalid_ranges():
    assert equal_source_ranges("","") == []
    assert rebase_range([],None,1) is None
    assert rebase_range(equal_source_ranges("abc","abc"),2,1) is None
