"""
Tests for pipeline/manifest.py append_warning helper (Fix 5b — Round 5).

Verifies:
  - append_warning creates the 'warnings' key when absent.
  - Multiple warnings accumulate in order.
  - Warning entries have the correct shape (stage, kind, message, details).
  - details dict is preserved; defaults to {} when not provided.
"""

import json
import pytest
from pathlib import Path

from pipeline.manifest import append_warning, create_manifest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """Create a minimal manifest.json in tmp_path and return tmp_path."""
    create_manifest(
        run_dir=tmp_path,
        run_id="test_run",
        cv_path="cv.txt",
        tor_path="tor.txt",
        params={"donor": "giz"},
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAppendWarning:
    def test_creates_warnings_key_when_absent(self, run_dir):
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert "warnings" not in manifest  # not present before first warning

        append_warning(run_dir, stage="compressor", kind="applied_false",
                       message="Compressor skipped.")

        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert "warnings" in manifest
        assert len(manifest["warnings"]) == 1

    def test_warning_has_correct_shape(self, run_dir):
        append_warning(run_dir, stage="fields_generator",
                       kind="generation_warnings_high",
                       message="Too many generation warnings.",
                       details={"count": 5, "threshold": 3})

        manifest = json.loads((run_dir / "manifest.json").read_text())
        w = manifest["warnings"][0]
        assert w["stage"] == "fields_generator"
        assert w["kind"] == "generation_warnings_high"
        assert w["message"] == "Too many generation warnings."
        assert w["details"]["count"] == 5

    def test_details_defaults_to_empty_dict_when_not_provided(self, run_dir):
        append_warning(run_dir, stage="compressor", kind="test", message="msg")
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert manifest["warnings"][0]["details"] == {}

    def test_multiple_warnings_accumulate(self, run_dir):
        append_warning(run_dir, stage="fields_generator", kind="a", message="First")
        append_warning(run_dir, stage="compressor", kind="b", message="Second")
        append_warning(run_dir, stage="content_reviewer", kind="c", message="Third")

        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert len(manifest["warnings"]) == 3
        assert manifest["warnings"][0]["message"] == "First"
        assert manifest["warnings"][2]["message"] == "Third"

    def test_other_manifest_keys_preserved(self, run_dir):
        append_warning(run_dir, stage="x", kind="y", message="z")
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert "run_id" in manifest
        assert "steps" in manifest
        assert "params" in manifest
