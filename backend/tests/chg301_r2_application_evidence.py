"""Read-only assertions connecting historical recipes to the approved delta."""
import hashlib
import json
import os
from pathlib import Path

from chg301_r2_formal_dependencies import ROOT, SOURCE_REPAIRS
from chg301_r2_delivery import source_manifest
from chg301_r2_node_qualification import file_sha


def historical_sources(before):
    run = Path(os.environ["CHG301_R2_APPLICATION_EVIDENCE"])
    current = json.loads((run/"manifest.json").read_bytes())
    actual = source_manifest()
    assert actual == current["source_accepted"]
    assert set(before) == set(actual)
    for path, expected in before.items():
        if actual[path] == expected:
            continue
        assert path in SOURCE_REPAIRS
        text = (ROOT/path).read_text()
        if path == "backend/Dockerfile":
            historical = Path("/private/tmp/chg301-r2-formal-ytnv04nm/backend-runner-r2/context/Dockerfile")
            assert file_sha(historical) == current["source_before"][path]
            old = historical.read_text()
            assert text == old.replace("    build-essential \\\n", "").replace("    libpq-dev \\\n", "")
            text = old
        for original, patched in reversed(SOURCE_REPAIRS[path]):
            assert text.count(patched) == 1
            text = text.replace(patched, original, 1)
        assert hashlib.sha256(text.encode()).hexdigest() == expected
    return actual
