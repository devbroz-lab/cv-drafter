"""
Smoke tests for new CVData schema fields introduced in Round 4 (R4-B + R4-E)
and DistilledToR schema fields introduced in Round 5 (R5-A).

Verifies:
  - Reference model instantiates with all optional fields.
  - CVData accepts references list and certification_declaration.
  - CVData accepts language_scale_direction with valid Literal values.
  - All new fields default correctly ([], "", None).
  - ScoringKeywords model instantiates and accepts populated lists.
  - DistilledToR accepts scoring_keywords with ScoringKeywords sub-model.
  - Backward compatibility: existing artifacts without new fields round-trip cleanly.
"""

import pytest
from pydantic import ValidationError

from models import CVData, Reference, ScoringKeywords, DistilledToR


# ---------------------------------------------------------------------------
# Reference model
# ---------------------------------------------------------------------------

class TestReferenceModel:
    def test_empty_reference_instantiates(self):
        ref = Reference()
        assert ref.name == ""
        assert ref.title == ""
        assert ref.organisation == ""
        assert ref.email == ""
        assert ref.phone == ""

    def test_populated_reference(self):
        ref = Reference(
            name="John Doe",
            title="Director",
            organisation="AfDB",
            email="john.doe@afdb.org",
            phone="+1-202-555-0100",
        )
        assert ref.name == "John Doe"
        assert ref.email == "john.doe@afdb.org"

    def test_partial_reference(self):
        ref = Reference(name="Jane Smith", email="jane@example.com")
        assert ref.name == "Jane Smith"
        assert ref.title == ""
        assert ref.organisation == ""


# ---------------------------------------------------------------------------
# CVData new fields
# ---------------------------------------------------------------------------

class TestCVDataNewFields:
    def test_references_defaults_to_empty_list(self):
        cv = CVData()
        assert cv.references == []

    def test_certification_declaration_defaults_to_empty_string(self):
        cv = CVData()
        assert cv.certification_declaration == ""

    def test_language_scale_direction_defaults_to_none(self):
        cv = CVData()
        assert cv.language_scale_direction is None

    def test_cv_data_accepts_references_list(self):
        cv = CVData(references=[Reference(name="A"), Reference(name="B")])
        assert len(cv.references) == 2
        assert cv.references[0].name == "A"

    def test_cv_data_accepts_certification_declaration(self):
        cv = CVData(certification_declaration="I, the undersigned, certify...")
        assert "certify" in cv.certification_declaration

    def test_language_scale_direction_accepts_1_best(self):
        cv = CVData(language_scale_direction="1_best")
        assert cv.language_scale_direction == "1_best"

    def test_language_scale_direction_accepts_1_worst(self):
        cv = CVData(language_scale_direction="1_worst")
        assert cv.language_scale_direction == "1_worst"

    def test_language_scale_direction_accepts_none(self):
        cv = CVData(language_scale_direction=None)
        assert cv.language_scale_direction is None

    def test_language_scale_direction_rejects_invalid(self):
        with pytest.raises(ValidationError):
            CVData(language_scale_direction="bad_value")


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_minimal_cv_data_round_trips(self):
        """CVData with only legacy fields serialises and deserialises cleanly."""
        cv = CVData(proposed_position="Energy Specialist")
        dumped = cv.model_dump()
        restored = CVData.model_validate(dumped)
        assert restored.proposed_position == "Energy Specialist"
        assert restored.references == []
        assert restored.certification_declaration == ""
        assert restored.language_scale_direction is None

    def test_existing_cv_data_json_with_no_new_fields_validates(self):
        """
        A cv_data.json written before Round 4 (no new keys) must still
        validate cleanly — the new fields carry defaults.
        """
        raw = {
            "personal_info": {},
            "proposed_position": "Consultant",
            "languages": [{
                "language": "English",
                "reading_raw": "fluent",
            }],
        }
        cv = CVData.model_validate(raw)
        assert cv.references == []
        assert cv.certification_declaration == ""
        assert cv.language_scale_direction is None


# ---------------------------------------------------------------------------
# ScoringKeywords + DistilledToR.scoring_keywords (R5-A — Round 5)
# ---------------------------------------------------------------------------

class TestScoringKeywordsModel:
    def test_scoring_keywords_instantiates_with_defaults(self):
        sk = ScoringKeywords()
        assert sk.role_implied == []
        assert sk.scope_implied == []
        assert sk.explicit == []

    def test_scoring_keywords_accepts_populated_lists(self):
        sk = ScoringKeywords(
            role_implied=["grid code", "tariff design"],
            scope_implied=["renewable energy", "distribution network"],
            explicit=["South Africa", "7 years"],
        )
        assert len(sk.role_implied) == 2
        assert "grid code" in sk.role_implied
        assert "South Africa" in sk.explicit

    def test_scoring_keywords_round_trips(self):
        sk = ScoringKeywords(role_implied=["a", "b"], explicit=["c"])
        restored = ScoringKeywords.model_validate(sk.model_dump())
        assert restored.role_implied == ["a", "b"]
        assert restored.explicit == ["c"]


class TestDistilledToRScoringKeywords:
    def test_distilled_tor_has_scoring_keywords_field(self):
        tor = DistilledToR()
        assert isinstance(tor.scoring_keywords, ScoringKeywords)
        assert tor.scoring_keywords.role_implied == []

    def test_distilled_tor_accepts_populated_scoring_keywords(self):
        tor = DistilledToR(
            position_title="Energy Expert",
            scoring_keywords=ScoringKeywords(
                role_implied=["grid code"],
                explicit=["South Africa"],
            ),
        )
        assert "grid code" in tor.scoring_keywords.role_implied
        assert "South Africa" in tor.scoring_keywords.explicit

    def test_distilled_tor_backward_compat_without_scoring_keywords(self):
        """Old tor_data.json (no scoring_keywords key) must validate cleanly."""
        raw = {
            "position_title": "Consultant",
            "sector_keywords": ["energy"],
            "key_tasks": ["Develop plan"],
        }
        tor = DistilledToR.model_validate(raw)
        assert isinstance(tor.scoring_keywords, ScoringKeywords)
        assert tor.scoring_keywords.role_implied == []

    def test_distilled_tor_scoring_keywords_from_nested_dict(self):
        """scoring_keywords as a dict in raw JSON should deserialise cleanly."""
        raw = {
            "position_title": "Regulatory Expert",
            "scoring_keywords": {
                "role_implied": ["tariff design", "regulatory accounting"],
                "scope_implied": ["electricity sector"],
                "explicit": ["Nigeria"],
            },
        }
        tor = DistilledToR.model_validate(raw)
        assert tor.scoring_keywords.role_implied == ["tariff design", "regulatory accounting"]
        assert tor.scoring_keywords.explicit == ["Nigeria"]
