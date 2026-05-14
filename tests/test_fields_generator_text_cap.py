"""
Tests for Fix 8 Part 3 — per-project text cap in fields_generator.py,
and Fix M Part 2 — restoration of original text after A4 returns.

Fix 8 Part 3 verifies:
  - activities_performed over cap is truncated to A4_INPUT_PROJECT_WORD_CAP
    words with a trailing "…" (U+2026).
  - main_project_features over cap is truncated.
  - Fields under the cap are unchanged.
  - Empty fields are unchanged (no "…" appended).
  - Other project fields (project_name, location, etc.) are not touched.
  - The original cv_data dict is not mutated (operates on a deep copy).
  - Both capped fields truncated independently.
  - Composition: _precompute_project_dates then _truncate_project_text_for_a4
    produces stable (idempotent) output.

Fix M Part 2 verifies:
  - _restore_truncated_project_text replaces activities_performed and
    main_project_features in A4's output with originals from the pre-truncation
    source, unconditionally by index.
  - Index mismatch (A4 returned different project count) → skip restoration.
  - Missing field in original → not injected into output.
  - Original inputs are not mutated.
  - Multiple projects all restored.
  - End-to-end: truncate then restore recovers the original values.
"""

import copy
import pytest

from pipeline.agents.fields_generator import (
    A4_INPUT_PROJECT_WORD_CAP,
    _A4_CAPPED_FIELDS,
    _truncate_project_text_for_a4,
    _restore_truncated_project_text,
    _precompute_project_dates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _words(n: int, word: str = "word") -> str:
    return " ".join([word] * n)


def _cv(projects: list[dict]) -> dict:
    return {"relevant_projects": projects}


# ---------------------------------------------------------------------------
# Core truncation behaviour
# ---------------------------------------------------------------------------

class TestTruncateProjectTextForA4Core:
    def test_over_cap_activities_performed_truncated(self):
        text_694 = _words(694)
        cv = _cv([{"project_name": "P", "activities_performed": text_694}])
        result = _truncate_project_text_for_a4(cv)
        truncated = result["relevant_projects"][0]["activities_performed"]
        word_count = len(truncated.rstrip("\u2026").split())
        assert word_count == A4_INPUT_PROJECT_WORD_CAP
        assert truncated.endswith("\u2026")

    def test_over_cap_main_project_features_truncated(self):
        text_300 = _words(300)
        cv = _cv([{"project_name": "P", "main_project_features": text_300}])
        result = _truncate_project_text_for_a4(cv)
        truncated = result["relevant_projects"][0]["main_project_features"]
        word_count = len(truncated.rstrip("\u2026").split())
        assert word_count == A4_INPUT_PROJECT_WORD_CAP
        assert truncated.endswith("\u2026")

    def test_exactly_at_cap_not_truncated(self):
        text_150 = _words(A4_INPUT_PROJECT_WORD_CAP)
        cv = _cv([{"project_name": "P", "activities_performed": text_150}])
        result = _truncate_project_text_for_a4(cv)
        assert result["relevant_projects"][0]["activities_performed"] == text_150
        assert not result["relevant_projects"][0]["activities_performed"].endswith("\u2026")

    def test_under_cap_unchanged(self):
        text_50 = _words(50)
        cv = _cv([{"project_name": "P", "activities_performed": text_50}])
        result = _truncate_project_text_for_a4(cv)
        assert result["relevant_projects"][0]["activities_performed"] == text_50

    def test_empty_activities_unchanged(self):
        cv = _cv([{"project_name": "P", "activities_performed": ""}])
        result = _truncate_project_text_for_a4(cv)
        assert result["relevant_projects"][0]["activities_performed"] == ""

    def test_missing_field_not_added(self):
        """If a field is absent from the project, it must not be injected."""
        cv = _cv([{"project_name": "P"}])
        result = _truncate_project_text_for_a4(cv)
        assert "activities_performed" not in result["relevant_projects"][0]

    def test_ellipsis_is_unicode_u2026(self):
        cv = _cv([{"project_name": "P", "activities_performed": _words(200)}])
        result = _truncate_project_text_for_a4(cv)
        truncated = result["relevant_projects"][0]["activities_performed"]
        assert truncated[-1] == "\u2026"


# ---------------------------------------------------------------------------
# Non-capped fields untouched
# ---------------------------------------------------------------------------

class TestNonCappedFieldsUntouched:
    def test_project_name_not_touched(self):
        cv = _cv([{"project_name": "A" * 500, "activities_performed": _words(200)}])
        result = _truncate_project_text_for_a4(cv)
        assert result["relevant_projects"][0]["project_name"] == "A" * 500

    def test_location_not_touched(self):
        cv = _cv([{"location": "Some long location text " * 20,
                   "activities_performed": _words(200)}])
        result = _truncate_project_text_for_a4(cv)
        assert "Some long location text " * 20 == result["relevant_projects"][0]["location"]

    def test_positions_held_not_touched(self):
        text = _words(300)
        cv = _cv([{"positions_held": text, "activities_performed": _words(200)}])
        result = _truncate_project_text_for_a4(cv)
        assert result["relevant_projects"][0]["positions_held"] == text


# ---------------------------------------------------------------------------
# Original dict not mutated
# ---------------------------------------------------------------------------

class TestOriginalNotMutated:
    def test_original_cv_data_unchanged(self):
        long_text = _words(694)
        cv = _cv([{"project_name": "P", "activities_performed": long_text}])
        original_copy = copy.deepcopy(cv)
        _truncate_project_text_for_a4(cv)
        assert cv == original_copy

    def test_result_is_independent_from_original(self):
        long_text = _words(300)
        cv = _cv([{"project_name": "P", "activities_performed": long_text}])
        result = _truncate_project_text_for_a4(cv)
        # Mutate result — original must not be affected
        result["relevant_projects"][0]["activities_performed"] = "changed"
        assert cv["relevant_projects"][0]["activities_performed"] == long_text


# ---------------------------------------------------------------------------
# Both fields truncated independently
# ---------------------------------------------------------------------------

class TestBothFieldsTruncatedIndependently:
    def test_both_over_cap_both_truncated(self):
        cv = _cv([{
            "project_name": "P",
            "activities_performed": _words(400, "act"),
            "main_project_features": _words(300, "feat"),
        }])
        result = _truncate_project_text_for_a4(cv)
        proj = result["relevant_projects"][0]
        assert proj["activities_performed"].endswith("\u2026")
        assert proj["main_project_features"].endswith("\u2026")
        assert len(proj["activities_performed"].rstrip("\u2026").split()) == A4_INPUT_PROJECT_WORD_CAP
        assert len(proj["main_project_features"].rstrip("\u2026").split()) == A4_INPUT_PROJECT_WORD_CAP

    def test_one_over_one_under(self):
        cv = _cv([{
            "project_name": "P",
            "activities_performed": _words(200),  # over cap
            "main_project_features": _words(50),   # under cap
        }])
        result = _truncate_project_text_for_a4(cv)
        proj = result["relevant_projects"][0]
        assert proj["activities_performed"].endswith("\u2026")
        assert not proj["main_project_features"].endswith("\u2026")


# ---------------------------------------------------------------------------
# Multiple projects
# ---------------------------------------------------------------------------

class TestMultipleProjects:
    def test_all_projects_processed(self):
        cv = _cv([
            {"project_name": f"P{i}", "activities_performed": _words(200)}
            for i in range(4)
        ])
        result = _truncate_project_text_for_a4(cv)
        for proj in result["relevant_projects"]:
            assert proj["activities_performed"].endswith("\u2026")


# ---------------------------------------------------------------------------
# Composition with _precompute_project_dates
# ---------------------------------------------------------------------------

class TestCompositionWithPrecompute:
    def test_precompute_then_cap_stable(self):
        cv = {
            "relevant_projects": [{
                "project_name": "P",
                "date_from": "2020",
                "date_to": "2022",
                "duration": "",
                "year": "",
                "activities_performed": _words(300),
            }]
        }
        step1 = _precompute_project_dates(cv)
        step2 = _truncate_project_text_for_a4(step1)
        # duration and year were filled by step 1
        proj = step2["relevant_projects"][0]
        assert proj["duration"] != ""
        # activities trimmed by step 2
        assert proj["activities_performed"].endswith("\u2026")
        # Running step 2 again is idempotent (already at/under cap)
        step3 = _truncate_project_text_for_a4(step2)
        assert step3["relevant_projects"][0]["activities_performed"] == \
               step2["relevant_projects"][0]["activities_performed"]


# ---------------------------------------------------------------------------
# Fix M Part 2 — _restore_truncated_project_text
# ---------------------------------------------------------------------------

class TestRestoreTruncatedProjectText:
    """_restore_truncated_project_text restores capped fields unconditionally."""

    def _make_original(self, activities: str, features: str = "") -> dict:
        proj = {"project_name": "P", "activities_performed": activities}
        if features:
            proj["main_project_features"] = features
        return {"relevant_projects": [proj]}

    def _make_out(self, activities: str, features: str = "") -> dict:
        proj = {"project_name": "P", "activities_performed": activities}
        if features:
            proj["main_project_features"] = features
        return {"relevant_projects": [proj]}

    def test_basic_restoration_replaces_truncated_text(self):
        full_text = _words(300)
        truncated = _words(A4_INPUT_PROJECT_WORD_CAP) + "\u2026"
        original = self._make_original(full_text)
        out = self._make_out(truncated)
        result = _restore_truncated_project_text(out, original)
        assert result["relevant_projects"][0]["activities_performed"] == full_text

    def test_main_project_features_also_restored(self):
        full_feat = _words(200, "feat")
        truncated_feat = _words(A4_INPUT_PROJECT_WORD_CAP, "feat") + "\u2026"
        original = {"relevant_projects": [{
            "project_name": "P",
            "activities_performed": "short",
            "main_project_features": full_feat,
        }]}
        out = {"relevant_projects": [{
            "project_name": "P",
            "activities_performed": "short",
            "main_project_features": truncated_feat,
        }]}
        result = _restore_truncated_project_text(out, original)
        assert result["relevant_projects"][0]["main_project_features"] == full_feat

    def test_restoration_is_unconditional(self):
        """Restoration replaces the text even when A4's output matches original
        (no truncation marker needed — original is always the source of truth)."""
        original = self._make_original("Same text, no ellipsis")
        out = self._make_out("Same text, no ellipsis")
        result = _restore_truncated_project_text(out, original)
        assert result["relevant_projects"][0]["activities_performed"] == \
               "Same text, no ellipsis"

    def test_index_mismatch_skips_restoration(self):
        """If A4 returns different number of projects, restoration is skipped."""
        original = {"relevant_projects": [
            {"project_name": "P0", "activities_performed": "original"},
            {"project_name": "P1", "activities_performed": "original"},
        ]}
        out = {"relevant_projects": [
            {"project_name": "P0", "activities_performed": "truncated\u2026"},
        ]}  # only 1 project — mismatch
        result = _restore_truncated_project_text(out, original)
        # Restoration skipped; A4's output returned unchanged
        assert result["relevant_projects"][0]["activities_performed"] == "truncated\u2026"

    def test_missing_field_in_original_not_injected(self):
        """If activities_performed is absent in original, it is not added to out."""
        original = {"relevant_projects": [{"project_name": "P"}]}
        out = {"relevant_projects": [{"project_name": "P", "activities_performed": "out text"}]}
        result = _restore_truncated_project_text(out, original)
        # activities_performed absent in original → not restored (field absent → skip)
        assert result["relevant_projects"][0]["activities_performed"] == "out text"

    def test_does_not_mutate_cv_data_out(self):
        original = self._make_original(_words(300))
        out = self._make_out(_words(A4_INPUT_PROJECT_WORD_CAP) + "\u2026")
        import copy as _copy
        out_copy = _copy.deepcopy(out)
        _restore_truncated_project_text(out, original)
        assert out == out_copy  # out not mutated

    def test_does_not_mutate_original_cv_data(self):
        original = self._make_original(_words(300))
        import copy as _copy
        original_copy = _copy.deepcopy(original)
        out = self._make_out(_words(A4_INPUT_PROJECT_WORD_CAP) + "\u2026")
        _restore_truncated_project_text(out, original)
        assert original == original_copy  # original not mutated

    def test_multiple_projects_all_restored(self):
        full_texts = [_words(200, f"w{i}") for i in range(4)]
        truncated_texts = [_words(A4_INPUT_PROJECT_WORD_CAP, f"w{i}") + "\u2026" for i in range(4)]
        original = {"relevant_projects": [
            {"project_name": f"P{i}", "activities_performed": full_texts[i]}
            for i in range(4)
        ]}
        out = {"relevant_projects": [
            {"project_name": f"P{i}", "activities_performed": truncated_texts[i]}
            for i in range(4)
        ]}
        result = _restore_truncated_project_text(out, original)
        for i in range(4):
            assert result["relevant_projects"][i]["activities_performed"] == full_texts[i]

    def test_integration_truncate_then_restore_is_identity(self):
        """
        End-to-end: applying truncate then restore recovers the original
        activities_performed and main_project_features exactly.
        """
        original = {
            "relevant_projects": [{
                "project_name": "P",
                "activities_performed": _words(300, "act"),
                "main_project_features": _words(200, "feat"),
            }]
        }
        truncated = _truncate_project_text_for_a4(original)
        # Simulate A4 output (copies truncated text back verbatim)
        a4_out = copy.deepcopy(truncated)
        restored = _restore_truncated_project_text(a4_out, original)
        assert restored["relevant_projects"][0]["activities_performed"] == \
               original["relevant_projects"][0]["activities_performed"]
        assert restored["relevant_projects"][0]["main_project_features"] == \
               original["relevant_projects"][0]["main_project_features"]
