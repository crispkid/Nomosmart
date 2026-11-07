import ast
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
    # Additional metadata must not make the all-versions projection contract
    # fail solely because the function call gained a keyword argument.
    function = next(node for node in ast.parse(route).body if isinstance(node, ast.FunctionDef) and node.name == "_project_document")
    versions = next(keyword.value for node in ast.walk(function) if isinstance(node, ast.Call)
                    for keyword in node.keywords if keyword.arg == "versions")
    assert isinstance(versions, ast.ListComp)
    assert ast.unparse(versions.generators[0].iter) == "versions"
    assert ast.unparse(versions.elt.func) == "_version_summary"
    assert ast.unparse(versions.elt.args[0]) == "row"
    keywords = {item.arg: ast.unparse(item.value) for item in versions.elt.keywords}
    assert keywords["expose_storage"] == "expose_storage"
    assert "metadata" in keywords
