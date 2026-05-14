"""
Tests for Fix J + Fix 8 Part 1 + Fix N + Fix 4 in pipeline/agents/cv_tor_mapper.py.

Fix J        — Python post-processing drops projects below the dynamic threshold.
Fix 8 Part 1 — Python truncates the kept set to MAX_PROJECTS_TO_KEEP.
Fix N        — Constants recalibrated; dynamic floor clamped to total.
Fix 4        — Python relevance scoring via _precompute_relevance_scores;
               duration pre-compute moved upstream to cv_tor_mapper.

Tests use internal helpers directly. No LLM calls.
"""

import copy
import pytest

from pipeline.agents.cv_tor_mapper import (
    MIN_PROJECTS_TO_KEEP,
    MAX_PROJECTS_TO_KEEP,
    SYSTEM_PROMPT_A3,
    _compute_threshold,
    _enforce_threshold_and_cap,
    _precompute_project_dates_for_mapper,
    _precompute_relevance_scores,
)


# ---------------------------------------------------------------------------
# _compute_threshold
# ---------------------------------------------------------------------------

class TestComputeThreshold:
    @pytest.mark.parametrize("n, expected", [
        (1, 0.30), (3, 0.30), (5, 0.30),
        (6, 0.40), (8, 0.40), (10, 0.40),
        (11, 0.50), (24, 0.50), (41, 0.50),
    ])
    def test_threshold_by_count(self, n, expected):
        assert _compute_threshold(n) == expected

    def test_prompt_threshold_values_match_python(self):
        """
        Guard against drift: the threshold values in SYSTEM_PROMPT_A3 must
        match the Python _compute_threshold return values for each bracket.
        """
        assert str(_compute_threshold(1))  in SYSTEM_PROMPT_A3   # 0.30
        assert str(_compute_threshold(6))  in SYSTEM_PROMPT_A3   # 0.40
        assert str(_compute_threshold(11)) in SYSTEM_PROMPT_A3   # 0.50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parsed(scores: list[dict]) -> dict:
    """Build a minimal parsed dict that _enforce_threshold_and_cap expects."""
    return {
        "data": {
            "relevant_projects": [
                {"project_name": s["project_name"]}
                for s in scores
                if s.get("kept")
            ]
        },
        "alignment": {
            "project_scores": [copy.deepcopy(s) for s in scores],
            "warnings": [],
        },
    }


def _make_score(name: str, score: float, kept: bool) -> dict:
    return {"project_name": name, "relevance_score": score, "kept": kept}


# ---------------------------------------------------------------------------
# Fix J — threshold enforcement
# ---------------------------------------------------------------------------

class TestThresholdEnforcement:
    def test_below_threshold_kept_project_is_dropped(self):
        """
        LLM marks a 0.45 project kept at total=11+ (new threshold=0.50).
        """
        scores = [_make_score(f"P{i:02d}", 0.65, True) for i in range(11)]
        scores.append(_make_score("Below", 0.45, True))   # below new 0.50 threshold
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}

        _enforce_threshold_and_cap(parsed, original)

        below_score = next(
            e for e in parsed["alignment"]["project_scores"]
            if e["project_name"] == "Below"
        )
        assert below_score["kept"] is False

    def test_at_threshold_not_dropped(self):
        """A project exactly at the threshold must NOT be dropped by threshold step.
        Use <=5 projects (thresh=0.30) with a project at exactly 0.30.
        """
        scores = [
            _make_score("High", 0.80, True),
            _make_score("Exact", 0.30, True),  # exactly at 0.30 threshold for total=2
        ]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)
        exact_score = next(
            e for e in parsed["alignment"]["project_scores"]
            if e["project_name"] == "Exact"
        )
        assert exact_score["kept"] is True

    def test_warning_added_when_projects_dropped(self):
        # 3 projects: threshold=0.30 (≤5); "Bad1" at 0.25 is below threshold
        scores = [
            _make_score("Good", 0.70, True),
            _make_score("Bad1", 0.25, True),
            _make_score("Bad2", 0.20, True),
        ]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)
        warnings = parsed["alignment"]["warnings"]
        assert any("threshold" in w.lower() for w in warnings)

    def test_no_warning_when_all_above_threshold(self):
        scores = [_make_score(f"P{i}", 0.70, True) for i in range(3)]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)
        warnings = parsed["alignment"]["warnings"]
        assert not any("threshold" in w.lower() for w in warnings)

    def test_already_dropped_projects_not_touched_when_minimum_satisfied(self):
        """
        LLM-dropped projects stay False when the minimum guarantee is already
        satisfied. Use 6 projects so effective_floor = min(MIN, 6) and
        5 kept projects exceed it regardless of MIN value.
        """
        scores = [
            _make_score("Kept1",   0.80, True),
            _make_score("Kept2",   0.75, True),
            _make_score("Kept3",   0.70, True),
            _make_score("Kept4",   0.65, True),
            _make_score("Kept5",   0.60, True),
            _make_score("Dropped", 0.25, False),  # LLM already dropped this
        ]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)
        dropped = next(e for e in parsed["alignment"]["project_scores"]
                       if e["project_name"] == "Dropped")
        # 4 kept projects already satisfy floor=3; Dropped stays False
        assert dropped["kept"] is False


# ---------------------------------------------------------------------------
# Minimum guarantee
# ---------------------------------------------------------------------------

class TestMinimumGuarantee:
    def test_restores_top_scoring_dropped_when_below_minimum(self):
        """
        When threshold enforcement drops all projects, the top-scoring ones
        must be restored to meet effective_floor (= min(3, total=3) = 3).
        New threshold for 3 projects (<=5) is 0.30, so scores below 0.30 drop.
        """
        scores = [
            _make_score("Best",   0.28, True),   # below 0.30 → dropped
            _make_score("Second", 0.25, True),   # below 0.30 → dropped
            _make_score("Third",  0.20, True),   # below 0.30 → dropped
        ]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)

        kept = [e for e in parsed["alignment"]["project_scores"] if e.get("kept")]
        # effective_floor = min(3, 3) = 3 → all three restored
        assert len(kept) == 3
        names = {e["project_name"] for e in kept}
        assert "Best" in names

    def test_minimum_guarantee_warning_added(self):
        # 1 project, score 0.25 → below thresh 0.30, dropped then restored
        scores = [_make_score("Only", 0.25, True)]
        original = [{"project_name": "Only"}]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)
        warnings = parsed["alignment"]["warnings"]
        assert any("minimum" in w.lower() or "restored" in w.lower() for w in warnings)

    def test_dynamic_floor_clamps_to_total(self):
        """
        A CV with only 2 projects: effective_floor = min(3, 2) = 2.
        All 2 projects are restored, never 3 (avoids infinite-loop hazard).
        """
        scores = [
            _make_score("P0", 0.25, True),   # below 0.30 → dropped
            _make_score("P1", 0.20, True),   # below 0.30 → dropped
        ]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)
        kept = [e for e in parsed["alignment"]["project_scores"] if e.get("kept")]
        assert len(kept) == 2   # clamped to total, NOT to MIN_PROJECTS_TO_KEEP=3


# ---------------------------------------------------------------------------
# Fix 8 Part 1 — maximum cap
# ---------------------------------------------------------------------------

class TestMaximumCap:
    def test_cap_truncates_to_max(self):
        """Use MAX+1 projects all above threshold → exactly MAX_PROJECTS_TO_KEEP kept."""
        n = MAX_PROJECTS_TO_KEEP + 1
        scores = [_make_score(f"P{i:02d}", 0.65 - i * 0.005, True) for i in range(n)]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)

        kept = [e for e in parsed["alignment"]["project_scores"] if e.get("kept")]
        assert len(kept) == MAX_PROJECTS_TO_KEEP

    def test_cap_keeps_highest_scoring(self):
        """After truncation, the kept set must be the top MAX_PROJECTS_TO_KEEP by score."""
        n = MAX_PROJECTS_TO_KEEP + 2
        scores = [_make_score(f"P{i:02d}", float(i) / 100 + 0.55, True) for i in range(n)]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)

        kept = sorted(
            [e for e in parsed["alignment"]["project_scores"] if e.get("kept")],
            key=lambda e: e["relevance_score"],
            reverse=True,
        )
        assert len(kept) == MAX_PROJECTS_TO_KEEP
        all_sorted = sorted(scores, key=lambda e: e["relevance_score"], reverse=True)
        expected_names = {e["project_name"] for e in all_sorted[:MAX_PROJECTS_TO_KEEP]}
        assert {e["project_name"] for e in kept} == expected_names

    def test_under_cap_not_truncated(self):
        scores = [_make_score(f"P{i}", 0.70, True) for i in range(4)]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)
        kept = [e for e in parsed["alignment"]["project_scores"] if e.get("kept")]
        assert len(kept) == 4

    def test_cap_warning_added_when_truncation_occurs(self):
        n = MAX_PROJECTS_TO_KEEP + 1
        scores = [_make_score(f"P{i:02d}", 0.65, True) for i in range(n)]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)
        warnings = parsed["alignment"]["warnings"]
        assert any("cap" in w.lower() or "max_projects" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# data.relevant_projects order
# ---------------------------------------------------------------------------

class TestProjectOrderPreserved:
    def test_output_order_matches_original_cv_order(self):
        """
        After enforcement, data.relevant_projects must follow the original
        CV document order, not the score order.
        """
        # Original CV order: Alpha, Beta, Gamma (different from score order)
        original = [
            {"project_name": "Alpha"},
            {"project_name": "Beta"},
            {"project_name": "Gamma"},
        ]
        # LLM scores in different order, all kept, all above threshold (total=3, thresh=0.30)
        scores = [
            _make_score("Gamma", 0.90, True),
            _make_score("Alpha", 0.80, True),
            _make_score("Beta",  0.75, True),
        ]
        parsed = {
            "data": {"relevant_projects": [
                {"project_name": "Gamma"},
                {"project_name": "Alpha"},
                {"project_name": "Beta"},
            ]},
            "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []},
        }
        _enforce_threshold_and_cap(parsed, original)
        result_names = [p["project_name"] for p in parsed["data"]["relevant_projects"]]
        assert result_names == ["Alpha", "Beta", "Gamma"]


# ---------------------------------------------------------------------------
# Composition: threshold + minimum + cap (Run 4 simulation)
# ---------------------------------------------------------------------------

class TestComposition:
    def test_run4_simulation(self):
        """
        Round 4 calibration: 24 total projects (threshold=0.50).
        10 above threshold, 8 LLM-kept below threshold (0.42–0.49), 6 LLM-dropped.
        After enforcement: 10 survive threshold; cap=10 so no truncation.
        """
        # 10 above new 0.50 threshold
        high = [_make_score(f"High{i}", 0.55 + i * 0.01, True) for i in range(10)]
        # 8 LLM kept but below new 0.50 threshold (0.42–0.49)
        low = [_make_score(f"Low{i}", 0.42 + i * 0.01, True) for i in range(8)]
        # 6 LLM-dropped
        dropped = [_make_score(f"Dropped{i}", 0.20, False) for i in range(6)]

        scores = high + low + dropped  # total = 24
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}

        _enforce_threshold_and_cap(parsed, original)

        kept = [e for e in parsed["alignment"]["project_scores"] if e.get("kept")]
        # After threshold (0.50): 10 high survive; 8 low dropped
        # After cap (10): exactly 10 kept, cap not exceeded
        assert len(kept) == 10
        kept_names = {e["project_name"] for e in kept}
        for h in high:
            assert h["project_name"] in kept_names

    def test_no_op_when_all_in_range(self):
        """When LLM output is already correct, enforcement makes no changes."""
        scores = [_make_score(f"P{i}", 0.70, True) for i in range(4)]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}

        _enforce_threshold_and_cap(parsed, original)

        kept = [e for e in parsed["alignment"]["project_scores"] if e.get("kept")]
        assert len(kept) == 4
        assert parsed["alignment"]["warnings"] == []


# ---------------------------------------------------------------------------
# Fix 4 — _precompute_relevance_scores
# ---------------------------------------------------------------------------

class TestPrecomputeRelevanceScores:
    def _make_cv(self, projects: list[dict]) -> dict:
        return {"relevant_projects": projects}

    def _make_tor(self, keywords: list[str] = None, countries: list[str] = None) -> dict:
        return {
            "scoring_keywords": {
                "role_implied": keywords or [],
                "scope_implied": [],
                "explicit": countries or [],
            },
            "country_experience_required": countries or [],
            "sector_keywords": keywords or [],
        }

    def test_returns_none_when_no_scoring_signal(self):
        cv = self._make_cv([{"project_name": "P", "activities_performed": ""}])
        tor = {"scoring_keywords": {}, "country_experience_required": []}
        assert _precompute_relevance_scores(cv, tor) is None

    def test_returns_dict_with_project_scores_when_keywords_present(self):
        cv = self._make_cv([{
            "project_name": "Grid Project",
            "activities_performed": "grid code development and tariff design",
        }])
        tor = self._make_tor(keywords=["grid code", "tariff design"])
        result = _precompute_relevance_scores(cv, tor)
        assert result is not None
        assert "project_scores" in result
        assert len(result["project_scores"]) == 1

    def test_project_score_shape(self):
        cv = self._make_cv([{"project_name": "P", "activities_performed": "grid code"}])
        tor = self._make_tor(keywords=["grid code"], countries=["Kenya"])
        result = _precompute_relevance_scores(cv, tor)
        score = result["project_scores"][0]
        assert "keyword_overlap_score" in score
        assert "keyword_matches" in score
        assert "country_overlap" in score
        assert "composite_score" in score
        assert "duration_years" in score

    def test_keyword_match_reflected_in_score(self):
        cv = self._make_cv([{"project_name": "P", "activities_performed": "grid code work"}])
        tor = self._make_tor(keywords=["grid code", "tariff design"])
        result = _precompute_relevance_scores(cv, tor)
        score = result["project_scores"][0]
        assert score["keyword_overlap_score"] == pytest.approx(0.5)
        assert "grid code" in score["keyword_matches"]

    def test_falls_back_to_legacy_sector_keywords(self):
        """When scoring_keywords is absent, falls back to sector_keywords."""
        cv = self._make_cv([{"project_name": "P", "activities_performed": "renewable energy"}])
        tor = {"sector_keywords": ["renewable energy"], "country_experience_required": []}
        result = _precompute_relevance_scores(cv, tor)
        assert result is not None
        assert result["project_scores"][0]["keyword_overlap_score"] == 1.0

    def test_scoring_note_present(self):
        cv = self._make_cv([{"project_name": "P", "activities_performed": "energy"}])
        tor = self._make_tor(keywords=["energy"])
        result = _precompute_relevance_scores(cv, tor)
        assert "scoring_note" in result


class TestDurationUpstreamPrecompute:
    def test_projects_get_duration_filled(self):
        cv = {"relevant_projects": [{
            "project_name": "P",
            "date_from": "January 2018",
            "date_to": "December 2020",
            "duration": "",
            "year": "",
        }]}
        result = _precompute_project_dates_for_mapper(cv)
        assert result["relevant_projects"][0]["duration"] != ""
        assert result["relevant_projects"][0]["year"] != ""

    def test_does_not_overwrite_existing_duration(self):
        cv = {"relevant_projects": [{
            "project_name": "P",
            "date_from": "2018",
            "date_to": "2020",
            "duration": "3 years",
            "year": "2018-2020",
        }]}
        result = _precompute_project_dates_for_mapper(cv)
        assert result["relevant_projects"][0]["duration"] == "3 years"

    def test_original_not_mutated(self):
        import copy
        cv = {"relevant_projects": [{"project_name": "P", "date_from": "2018", "date_to": "2020", "duration": ""}]}
        original = copy.deepcopy(cv)
        _precompute_project_dates_for_mapper(cv)
        assert cv == original


# ---------------------------------------------------------------------------
# Issue DD — JSON-only output contract (A3)
# ---------------------------------------------------------------------------

class TestSystemPromptA3JsonOnly:
    """A3 prompt must enforce the JSON-only output contract."""

    def test_output_contract_section_present(self):
        assert "Output contract" in SYSTEM_PROMPT_A3

    def test_first_char_rule_present(self):
        assert "FIRST non-whitespace" in SYSTEM_PROMPT_A3
