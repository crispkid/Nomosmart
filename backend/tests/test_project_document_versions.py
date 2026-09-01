from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_project_document_summary_includes_all_version_summaries() -> None:
    schemas = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    route = (ROOT / "backend" / "app" / "api" / "routes" / "documents.py").read_text(encoding="utf-8")

    assert "versions: list[DocumentVersionSummary] = Field(default_factory=list)" in schemas
    assert re.search(r"def\s+_project_document\(\s*session:\s*Session,\s*document:\s*Document", route)
    assert "select(DocumentVersion)" in route
    assert "DocumentVersion.document_id == document.id" in route
    assert "versions=[_version_summary(row, expose_storage=expose_storage) for row in versions]" in route
