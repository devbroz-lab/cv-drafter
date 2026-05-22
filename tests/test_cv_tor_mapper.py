"""
Tests for Fix J + Fix 8 Part 1 + R4-A + R5-B + R7.5-D + R7.5-G in
pipeline/agents/cv_tor_mapper.py.

Fix J        — Python post-processing drops projects below the dynamic threshold.
Fix 8 Part 1 — Python truncates the kept set to MAX_PROJECTS_TO_KEEP.
R4-A        — Constants recalibrated; dynamic floor clamped to total.
R5-B        — Python relevance scoring via _precompute_relevance_scores;
               duration pre-compute moved upstream to cv_tor_mapper.
R7.5-C     — MIN=10, MAX=30 constants (Round 7.5).
R7.5-D     — _protect_current_role: restore dropped Present project after cap.
R7.5-G       — _sort_by_date_desc: primary_key="date_to" for countries.

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
    _protect_current_role,
    _sort_by_date_desc,
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
        satisfied. With MIN=10, use 12 projects total (effective_floor=10) and
        have 10 LLM-kept projects — floor is already met so the dropped one
        stays dropped.
        """
        scores = [
            _make_score("Kept1",  0.80, True),
            _make_score("Kept2",  0.75, True),
            _make_score("Kept3",  0.70, True),
            _make_score("Kept4",  0.65, True),
            _make_score("Kept5",  0.60, True),
            _make_score("Kept6",  0.58, True),
            _make_score("Kept7",  0.56, True),
            _make_score("Kept8",  0.54, True),
            _make_score("Kept9",  0.52, True),
            _make_score("Kept10", 0.51, True),
            _make_score("Dropped1", 0.25, False),  # LLM already dropped these
            _make_score("Dropped2", 0.20, False),
        ]
        original = [{"project_name": s["project_name"]} for s in scores]
        parsed = {"data": {"relevant_projects": copy.deepcopy(original)},
                  "alignment": {"project_scores": copy.deepcopy(scores), "warnings": []}}
        _enforce_threshold_and_cap(parsed, original)
        dropped1 = next(e for e in parsed["alignment"]["project_scores"]
                        if e["project_name"] == "Dropped1")
        # 10 kept projects satisfy effective_floor=min(10, 12)=10; Dropped stays False
        assert dropped1["kept"] is False


# ---------------------------------------------------------------------------
# Minimum guarantee
# ---------------------------------------------------------------------------

class TestMinimumGuarantee:
    def test_restores_top_scoring_dropped_when_below_minimum(self):
        """
        When threshold enforcement drops all projects, the top-scoring ones
        must be restored to meet effective_floor (= min(10, total=3) = 3).
        Threshold for 3 projects (<=5) is 0.30, so scores below 0.30 drop.
        effective_floor clamps to 3 (total), so all three are restored.
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
        # effective_floor = min(10, 3) = 3 → all three restored
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
        A CV with only 2 projects: effective_floor = min(10, 2) = 2.
        All 2 projects are restored, never 10 (avoids restoring non-existent projects).
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
        assert len(kept) == 2   # clamped to total, NOT to MIN_PROJECTS_TO_KEEP=10


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
        After enforcement: 10 survive threshold; cap=30 so no truncation.
        effective_floor=min(10,24)=10 = kept_count so minimum guarantee is a no-op.
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
# R5-B — _precompute_relevance_scores
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


# ---------------------------------------------------------------------------
# R7.5-C — MIN/MAX constant values (Round 7.5)
# ---------------------------------------------------------------------------

class TestPPAConstants:
    def test_min_projects_is_10(self):
        assert MIN_PROJECTS_TO_KEEP == 10

    def test_max_projects_is_30(self):
        assert MAX_PROJECTS_TO_KEEP == 30


# ---------------------------------------------------------------------------
# R7.5-D — _protect_current_role (Round 7.5)
# ---------------------------------------------------------------------------

def _make_full_parsed(scores: list[dict], original_projects: list[dict]) -> dict:
    """Build a minimal parsed dict for _protect_current_role testing."""
    kept_names = {s["project_name"] for s in scores if s.get("kept")}
    return {
        "data": {
            "relevant_projects": [
                p for p in original_projects if p.get("project_name", "") in kept_names
            ]
        },
        "alignment": {
            "project_scores": [copy.deepcopy(s) for s in scores],
            "warnings": [],
        },
    }


class TestProtectCurrentRole:
    def _orig(self, name: str, date_from: str, date_to: str) -> dict:
        return {"project_name": name, "date_from": date_from, "date_to": date_to}

    def test_restores_dropped_present_project(self):
        """A 'Present' project dropped by cap is unconditionally restored."""
        scores = [
            {"project_name": "CurrentRole", "relevance_score": 0.30, "kept": False},
            {"project_name": "OldRole",     "relevance_score": 0.80, "kept": True},
        ]
        original = [
            self._orig("CurrentRole", "January 2021", "Present"),
            self._orig("OldRole",     "January 2015", "December 2020"),
        ]
        parsed = _make_full_parsed(scores, original)
        _protect_current_role(parsed, original)

        score_entry = next(e for e in parsed["alignment"]["project_scores"]
                           if e["project_name"] == "CurrentRole")
        assert score_entry["kept"] is True
        proj_names = [p["project_name"] for p in parsed["data"]["relevant_projects"]]
        assert "CurrentRole" in proj_names

    def test_no_op_when_present_project_already_kept(self):
        """If the 'Present' project was already kept, no change is made."""
        scores = [
            {"project_name": "CurrentRole", "relevance_score": 0.80, "kept": True},
            {"project_name": "OldRole",     "relevance_score": 0.70, "kept": True},
        ]
        original = [
            self._orig("CurrentRole", "January 2021", "Present"),
            self._orig("OldRole",     "January 2015", "December 2020"),
        ]
        parsed = _make_full_parsed(scores, original)
        _protect_current_role(parsed, original)

        assert parsed["alignment"]["warnings"] == []

    def test_no_op_when_no_present_projects(self):
        """If no project has date_to = Present, nothing is changed."""
        scores = [
            {"project_name": "P1", "relevance_score": 0.20, "kept": False},
        ]
        original = [self._orig("P1", "2015", "2018")]
        parsed = _make_full_parsed(scores, original)
        _protect_current_role(parsed, original)

        score_entry = parsed["alignment"]["project_scores"][0]
        assert score_entry["kept"] is False
        assert parsed["alignment"]["warnings"] == []

    def test_picks_latest_date_from_among_multiple_present_projects(self):
        """When multiple 'Present' projects are dropped, restore the latest date_from."""
        scores = [
            {"project_name": "Current2021", "relevance_score": 0.30, "kept": False},
            {"project_name": "Current2018", "relevance_score": 0.35, "kept": False},
            {"project_name": "OldRole",     "relevance_score": 0.80, "kept": True},
        ]
        original = [
            self._orig("Current2021", "January 2021", "Present"),
            self._orig("Current2018", "January 2018", "Present"),
            self._orig("OldRole",     "January 2010", "December 2017"),
        ]
        parsed = _make_full_parsed(scores, original)
        _protect_current_role(parsed, original)

        # Only the most-recent "Present" project (2021) should be restored
        current2021 = next(e for e in parsed["alignment"]["project_scores"]
                           if e["project_name"] == "Current2021")
        current2018 = next(e for e in parsed["alignment"]["project_scores"]
                           if e["project_name"] == "Current2018")
        assert current2021["kept"] is True
        assert current2018["kept"] is False

    def test_warning_emitted_when_project_restored(self):
        scores = [
            {"project_name": "CurrentRole", "relevance_score": 0.25, "kept": False},
        ]
        original = [self._orig("CurrentRole", "March 2022", "Present")]
        parsed = _make_full_parsed(scores, original)
        _protect_current_role(parsed, original)

        warnings = parsed["alignment"]["warnings"]
        assert len(warnings) == 1
        assert "R7.5-D" in warnings[0]
        assert "CurrentRole" in warnings[0]

    def test_case_insensitive_present_detection(self):
        """'ongoing' and 'current' (case-insensitive) also trigger protection."""
        for date_to in ["ongoing", "PRESENT", "Current", "Ongoing"]:
            scores = [{"project_name": "P", "relevance_score": 0.20, "kept": False}]
            original = [self._orig("P", "2020", date_to)]
            parsed = _make_full_parsed(scores, original)
            _protect_current_role(parsed, original)
            score = parsed["alignment"]["project_scores"][0]
            assert score["kept"] is True, f"Failed for date_to='{date_to}'"


# ---------------------------------------------------------------------------
# R7.5-G — _sort_by_date_desc primary_key="date_to" (Round 7.5)
# ---------------------------------------------------------------------------

class TestSortByDateDescRR:
    def _country(self, name: str, date_from: str, date_to: str) -> dict:
        return {"country": name, "date_from": date_from, "date_to": date_to}

    def test_present_floats_to_top_with_date_to_sort(self):
        """'Present' date_to sorts highest when primary_key='date_to'."""
        countries = [
            self._country("Kosovo", "January 1999", "Present"),
            self._country("Albania", "January 2014", "December 2018"),
            self._country("Serbia", "January 2010", "December 2013"),
        ]
        result = _sort_by_date_desc(countries, primary_key="date_to")
        assert result[0]["country"] == "Kosovo"

    def test_date_to_desc_ordering(self):
        """Countries are ordered newest date_to first."""
        countries = [
            self._country("A", "2010", "2015"),
            self._country("B", "2010", "2020"),
            self._country("C", "2010", "2012"),
        ]
        result = _sort_by_date_desc(countries, primary_key="date_to")
        assert result[0]["country"] == "B"
        assert result[1]["country"] == "A"
        assert result[2]["country"] == "C"

    def test_projects_still_sort_by_date_from_default(self):
        """Default primary_key='date_from' behaviour is unchanged for projects."""
        projects = [
            {"project_name": "Old", "date_from": "January 2010", "date_to": "December 2012"},
            {"project_name": "New", "date_from": "January 2020", "date_to": "December 2021"},
        ]
        result = _sort_by_date_desc(projects)
        assert result[0]["project_name"] == "New"
