"""
Tests for the recovery-only project-text trimming helpers in
``pipeline.precompute_utils``: ``truncate_text_to_words`` and
``truncate_project_text``.

History: the old per-agent input caps (``_truncate_project_text_for_a4`` /
``_truncate_project_text_for_a6``, R6-E/Fix-8) were removed in R7-J/R7-K. The
happy path no longer truncates A4/A6 input. ``truncate_project_text`` is the
successor — invoked ONLY from each agent's ``reduce_input`` callback to shrink
an oversized request after a parse/truncation failure, never on the happy path.
"""

import copy

from pipeline.precompute_utils import truncate_project_text, truncate_text_to_words

_MARKER = " […]"


def _words(n: int, word: str = "word") -> str:
    return " ".join([word] * n)


def _cv(projects: list[dict]) -> dict:
    return {"relevant_projects": projects}


class TestTruncateTextToWords:
    def test_over_cap_truncated_with_marker(self):
        out = truncate_text_to_words(_words(300), 150)
        assert out.endswith(_MARKER)
        assert len(out[: -len(_MARKER)].split()) == 150

    def test_exactly_at_cap_unchanged(self):
        text = _words(150)
        assert truncate_text_to_words(text, 150) == text

    def test_under_cap_unchanged(self):
        text = _words(50)
        assert truncate_text_to_words(text, 150) == text

    def test_empty_returns_empty(self):
        assert truncate_text_to_words("", 150) == ""


class TestTruncateProjectText:
    def test_both_capped_fields_truncated(self):
        cv = _cv([{
            "project_name": "P",
            "activities_performed": _words(400, "act"),
            "main_project_features": _words(300, "feat"),
        }])
        result = truncate_project_text(cv, 120)
        proj = result["relevant_projects"][0]
        assert proj["activities_performed"].endswith(_MARKER)
        assert proj["main_project_features"].endswith(_MARKER)
        assert len(proj["activities_performed"][: -len(_MARKER)].split()) == 120
        assert len(proj["main_project_features"][: -len(_MARKER)].split()) == 120

    def test_under_cap_field_unchanged(self):
        cv = _cv([{"project_name": "P", "activities_performed": _words(50)}])
        result = truncate_project_text(cv, 120)
        assert result["relevant_projects"][0]["activities_performed"] == _words(50)

    def test_empty_field_unchanged(self):
        cv = _cv([{"project_name": "P", "activities_performed": ""}])
        result = truncate_project_text(cv, 120)
        assert result["relevant_projects"][0]["activities_performed"] == ""

    def test_missing_field_not_added(self):
        cv = _cv([{"project_name": "P"}])
        result = truncate_project_text(cv, 120)
        assert "activities_performed" not in result["relevant_projects"][0]

    def test_non_capped_fields_untouched(self):
        cv = _cv([{
            "project_name": "A" * 500,
            "positions_held": _words(300),
            "activities_performed": _words(200),
        }])
        result = truncate_project_text(cv, 120)
        proj = result["relevant_projects"][0]
        assert proj["project_name"] == "A" * 500
        assert proj["positions_held"] == _words(300)  # not in default fields

    def test_custom_fields_argument(self):
        cv = _cv([{"project_name": "P", "positions_held": _words(300)}])
        result = truncate_project_text(cv, 50, fields=("positions_held",))
        assert result["relevant_projects"][0]["positions_held"].endswith(_MARKER)

    def test_original_not_mutated(self):
        cv = _cv([{"project_name": "P", "activities_performed": _words(300)}])
        original = copy.deepcopy(cv)
        truncate_project_text(cv, 120)
        assert cv == original

    def test_multiple_projects_all_processed(self):
        cv = _cv([
            {"project_name": f"P{i}", "activities_performed": _words(300)}
            for i in range(4)
        ])
        result = truncate_project_text(cv, 120)
        for proj in result["relevant_projects"]:
            assert proj["activities_performed"].endswith(_MARKER)

    def test_tightening_cap_shrinks_further(self):
        """Mirrors the reduce_input escalation (200 -> 120 words)."""
        cv = _cv([{"project_name": "P", "activities_performed": _words(500)}])
        first = truncate_project_text(cv, 200)["relevant_projects"][0]["activities_performed"]
        second = truncate_project_text(cv, 120)["relevant_projects"][0]["activities_performed"]
        assert len(first[: -len(_MARKER)].split()) == 200
        assert len(second[: -len(_MARKER)].split()) == 120
