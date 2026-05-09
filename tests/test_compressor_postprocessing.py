"""
Tests for Agent 6 (Compressor) post-processing logic.

Does NOT make LLM calls.  Instead tests:
  - CompressionResult Pydantic validation (including new fields)
  - _count_compressible_words wrapper still works
  - restore_protected_fields integration (via precompute_utils)
  - generation_warnings passthrough expectation
"""

import pytest
from models import CompressionResult, FieldShortened
from pipeline.agents.compressor import PROTECTED_FIELDS, _count_compressible_words
from pipeline.precompute_utils import (
    count_compressible_words_total,
    restore_protected_fields,
)


# ---------------------------------------------------------------------------
# CompressionResult model
# ---------------------------------------------------------------------------

class TestCompressionResultModel:
    def test_minimal_valid(self):
        cr = CompressionResult(applied=True, words_before=500, words_after=400)
        assert cr.applied is True
        assert cr.target_not_reached is False
        assert cr.protected_field_restorations == []
        assert cr.fields_shortened == []

    def test_target_not_reached_flag(self):
        cr = CompressionResult(
            applied=True,
            words_before=600,
            words_after=520,
            target_not_reached=True,
        )
        assert cr.target_not_reached is True

    def test_protected_field_restorations_populated(self):
        cr = CompressionResult(
            applied=True,
            words_before=500,
            words_after=490,
            protected_field_restorations=["personal_info", "education"],
        )
        assert cr.protected_field_restorations == ["personal_info", "education"]

    def test_field_shortened_model(self):
        fs = FieldShortened(field="relevant_projects", subfield="[0].activities_performed",
                            words_before=60, words_after=40)
        assert fs.field == "relevant_projects"
        assert fs.words_before == 60
        assert fs.words_after == 40

    def test_model_validate_from_dict(self):
        raw = {
            "applied": True,
            "words_before": 500,
            "words_after": 400,
            "target_words": 450,
            "ratio_applied": False,
            "target_not_reached": False,
            "fields_shortened": [
                {"field": "key_qualifications", "subfield": "[0]",
                 "words_before": 30, "words_after": 20}
            ],
        }
        cr = CompressionResult.model_validate(raw)
        assert cr.words_before == 500
        assert len(cr.fields_shortened) == 1
        assert cr.fields_shortened[0].field == "key_qualifications"

    def test_model_validate_missing_optional_fields(self):
        # target_not_reached and protected_field_restorations are optional
        raw = {"applied": False, "words_before": 300, "words_after": 300}
        cr = CompressionResult.model_validate(raw)
        assert cr.target_not_reached is False
        assert cr.protected_field_restorations == []

    def test_model_dump_round_trip(self):
        cr = CompressionResult(
            applied=True,
            words_before=500,
            words_after=400,
            target_not_reached=True,
            protected_field_restorations=["personal_info"],
        )
        d = cr.model_dump()
        cr2 = CompressionResult.model_validate(d)
        assert cr2.target_not_reached is True
        assert cr2.protected_field_restorations == ["personal_info"]


# ---------------------------------------------------------------------------
# _count_compressible_words (wrapper)
# ---------------------------------------------------------------------------

class TestCountCompressibleWords:
    def test_wrapper_matches_utility(self):
        cv = {
            "relevant_projects": [
                {"activities_performed": "Led grid work", "main_project_features": "Upgraded lines"}
            ],
            "key_qualifications": ["Expert in solar"],
        }
        assert _count_compressible_words(cv) == count_compressible_words_total(cv)

    def test_empty(self):
        assert _count_compressible_words({}) == 0


# ---------------------------------------------------------------------------
# PROTECTED_FIELDS constant
# ---------------------------------------------------------------------------

class TestProtectedFieldsConstant:
    def test_expected_fields_present(self):
        for field in (
            "personal_info", "education", "languages", "proposed_position",
            "category", "employer", "years_with_firm",
        ):
            assert field in PROTECTED_FIELDS, f"{field!r} missing from PROTECTED_FIELDS"


# ---------------------------------------------------------------------------
# restore_protected_fields — integration with compressor's PROTECTED_FIELDS
# ---------------------------------------------------------------------------

class TestRestoreIntegration:
    def _make_cv(self, name: str, other: str) -> dict:
        return {
            "personal_info": {"first_names": name},
            "other_relevant_info": other,
        }

    def test_restored_field_is_from_original(self):
        original = self._make_cv("Alice", "Original info")
        modified = self._make_cv("CHANGED", "Compressed info")
        restored, paths = restore_protected_fields(original, modified, PROTECTED_FIELDS)
        assert "personal_info" in paths
        assert restored["personal_info"]["first_names"] == "Alice"
        # Non-protected field should retain the modified value
        assert restored["other_relevant_info"] == "Compressed info"

    def test_no_change_means_no_restoration(self):
        original = self._make_cv("Alice", "info")
        modified = self._make_cv("Alice", "compressed info")
        _, paths = restore_protected_fields(original, modified, PROTECTED_FIELDS)
        assert "personal_info" not in paths

    def test_words_after_recomputed_post_restoration(self):
        """
        Simulate the post-processing flow: after restore, words_after should
        be recomputed from the restored data, not from the modified data.
        """
        original = {
            "personal_info": {"first_names": "Alice"},
            "key_qualifications": ["Long qualification text here with many words"],
        }
        # LLM compressed key_qualifications but also touched personal_info
        modified = {
            "personal_info": {"first_names": "ALTERED"},
            "key_qualifications": ["Short text"],
        }
        restored, _ = restore_protected_fields(original, modified, PROTECTED_FIELDS)
        words_after = count_compressible_words_total(restored)
        # key_qualifications was compressed (not protected), personal_info was restored (protected, not counted)
        assert words_after == count_compressible_words_total(
            {"key_qualifications": ["Short text"]}
        )
