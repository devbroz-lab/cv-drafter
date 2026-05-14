"""
Tests for A1 (CV Extractor) prompt instructions — Fix Q, Fix O, Fix R, Fix U,
Fix V, Fix W.

These tests do NOT call the LLM.  They assert that required marker phrases
are present in SYSTEM_PROMPT_A1 so that accidental future edits removing
routing or detection instructions are caught immediately.

Fix Q — other_skills routing: "Other skills" section label → other_skills field.
Fix O — language scale direction detection: emit language_scale_direction.
Fix R — references and certification_declaration extraction.
Fix U — unfilled placeholder detection: append extraction_warnings entry.
Fix V — merged-cell two-column project table: extract project_name from left column.
Fix W — date inversion auto-correct across all four date-field types.
"""

from pipeline.agents.cv_extractor import SYSTEM_PROMPT_A1


# ---------------------------------------------------------------------------
# Fix Q — other_skills / certifications routing
# ---------------------------------------------------------------------------

class TestSystemPromptA1OtherSkillsRouting:
    """Other skills routing section must be present in SYSTEM_PROMPT_A1."""

    def test_other_skills_routing_section_present(self):
        assert "Other skills" in SYSTEM_PROMPT_A1 or \
               "other_skills" in SYSTEM_PROMPT_A1

    def test_label_routing_examples_present(self):
        """At least three field-routing examples must appear in the prompt."""
        lower = SYSTEM_PROMPT_A1.lower()
        routing_labels = [
            "other_skills",
            "certifications",
            "training",
            "membership_professional_bodies",
        ]
        found = sum(1 for label in routing_labels if label in lower)
        assert found >= 3, (
            f"Expected at least 3 routing labels in prompt, found {found}: "
            f"{[l for l in routing_labels if l in lower]}"
        )

    def test_membership_routing_mentioned(self):
        assert "membership_professional_bodies" in SYSTEM_PROMPT_A1 or \
               "membership" in SYSTEM_PROMPT_A1.lower()


# ---------------------------------------------------------------------------
# Fix O — language scale direction detection
# ---------------------------------------------------------------------------

class TestSystemPromptA1ScaleDirection:
    """Scale direction detection section must be present in SYSTEM_PROMPT_A1."""

    def test_scale_direction_detection_section_present(self):
        lower = SYSTEM_PROMPT_A1.lower()
        assert "scale direction" in lower or \
               "language_scale_direction" in SYSTEM_PROMPT_A1 or \
               "1_best" in SYSTEM_PROMPT_A1 or \
               "1_worst" in SYSTEM_PROMPT_A1

    def test_direction_values_documented(self):
        """Both direction values must appear in the prompt."""
        assert "1_best" in SYSTEM_PROMPT_A1
        assert "1_worst" in SYSTEM_PROMPT_A1


# ---------------------------------------------------------------------------
# Fix R — references and certification_declaration
# ---------------------------------------------------------------------------

class TestSystemPromptA1ReferenceExtraction:
    """References and certification_declaration extraction must be documented."""

    def test_references_section_present(self):
        assert "references" in SYSTEM_PROMPT_A1.lower() or \
               "References" in SYSTEM_PROMPT_A1

    def test_certification_declaration_section_present(self):
        assert "certification_declaration" in SYSTEM_PROMPT_A1 or \
               "certification" in SYSTEM_PROMPT_A1.lower()


# ---------------------------------------------------------------------------
# Fix U — unfilled placeholder detection
# ---------------------------------------------------------------------------

class TestSystemPromptA1UnfilledPlaceholder:
    """Placeholder detection section must be present in SYSTEM_PROMPT_A1."""

    def test_unfilled_placeholder_detection_section_present(self):
        lower = SYSTEM_PROMPT_A1.lower()
        assert "unfilled placeholder" in lower or \
               "placeholder" in lower

    def test_extraction_warnings_format_documented(self):
        """The prompt must show the warning format pattern."""
        assert "extraction_warnings" in SYSTEM_PROMPT_A1
        # The prompt must give a concrete example using the field_path format
        assert "contains likely unfilled placeholder" in SYSTEM_PROMPT_A1

    def test_placeholder_pattern_examples_present(self):
        """At least some common placeholder patterns must be mentioned."""
        lower = SYSTEM_PROMPT_A1.lower()
        patterns_mentioned = sum([
            "uppercase" in lower or "uppercase letter" in lower,
            "[years]" in lower or "[number]" in lower or "bracket" in lower,
            "underscore" in lower or "__" in SYSTEM_PROMPT_A1,
        ])
        assert patterns_mentioned >= 2, (
            "Expected at least 2 placeholder pattern examples in prompt"
        )


# ---------------------------------------------------------------------------
# Fix V — merged-cell and two-column project table extraction
# ---------------------------------------------------------------------------

class TestSystemPromptA1MergedCellExtraction:
    """Merged-cell project table extraction section must be present in SYSTEM_PROMPT_A1."""

    def test_merged_cell_project_section_present(self):
        """The section heading must appear in the prompt."""
        assert "Merged-cell and two-column project tables" in SYSTEM_PROMPT_A1 or \
               "merged-cell" in SYSTEM_PROMPT_A1.lower()

    def test_left_column_extraction_rule_documented(self):
        """The left-column extraction rule must be documented."""
        lower = SYSTEM_PROMPT_A1.lower()
        assert "left column" in lower, (
            "Expected 'left column' extraction rule in prompt"
        )

    def test_project_name_extraction_warning_documented(self):
        """The warning format for undeterminable project_name must be documented."""
        assert "project_name could not be determined" in SYSTEM_PROMPT_A1 or \
               "merged-cell or missing title" in SYSTEM_PROMPT_A1


# ---------------------------------------------------------------------------
# Fix W — date inversion auto-correct across all four date-field types
# ---------------------------------------------------------------------------

class TestSystemPromptA1DateOrdering:
    """Date ordering validation section must be present in SYSTEM_PROMPT_A1."""

    def test_date_ordering_section_present(self):
        """The section heading must appear in the prompt."""
        assert "Date ordering validation" in SYSTEM_PROMPT_A1

    def test_swap_rule_documented(self):
        """The swap-and-warn rule must be described."""
        assert "inverted at source" in SYSTEM_PROMPT_A1 or \
               "swapped during" in SYSTEM_PROMPT_A1

    def test_all_four_date_fields_covered(self):
        """All four field types that use date pairs must be named in the section."""
        for field in (
            "relevant_projects",
            "education",
            "employment_record",
            "countries_of_experience",
        ):
            assert field in SYSTEM_PROMPT_A1, (
                f"Expected '{field}' to be named in the date ordering section"
            )


# ---------------------------------------------------------------------------
# Date of birth — Month D YYYY (distinct from range-date Month YYYY)
# ---------------------------------------------------------------------------

class TestSystemPromptA1DateOfBirthFormat:
    """date_of_birth must use full day format per A1 prompt."""

    def test_dob_day_format_rule_present(self):
        assert "Month D YYYY" in SYSTEM_PROMPT_A1
        assert "date_of_birth" in SYSTEM_PROMPT_A1

    def test_dob_example_or_dd_mm_pattern_in_prompt(self):
        """Prompt must mention DD.MM.YYYY conversion or give the canonical example."""
        lower = SYSTEM_PROMPT_A1.lower()
        assert "7.07.1961" in SYSTEM_PROMPT_A1 or "dd.mm.yyyy" in lower


# ---------------------------------------------------------------------------
# Issue CC — employment-only fallback for empty relevant_projects
# ---------------------------------------------------------------------------

class TestSystemPromptA1EmploymentFallback:
    """Employment-only fallback section must be present in SYSTEM_PROMPT_A1."""

    def test_employment_fallback_section_present(self):
        """Key warning string that triggers the fallback must appear in the prompt."""
        assert (
            "No dedicated project section found" in SYSTEM_PROMPT_A1
            or "employment-only fallback" in SYSTEM_PROMPT_A1.lower()
        )

    def test_giz_never_empty_rule_present(self):
        """GIZ section must contain an unambiguous NEVER-empty guarantee."""
        assert "NEVER" in SYSTEM_PROMPT_A1 or "never" in SYSTEM_PROMPT_A1

    def test_fallback_field_mapping_documented(self):
        """Key mapping terms must appear in the prompt so the LLM knows which fields to use."""
        for term in ("main_project_features", "company"):
            assert term in SYSTEM_PROMPT_A1, (
                f"Expected field mapping term '{term}' in employment fallback section"
            )

    def test_activities_performed_left_empty_in_fallback(self):
        """Prompt must state that activities_performed is left empty in the employment fallback."""
        assert "activities_performed" in SYSTEM_PROMPT_A1
        # The prompt must indicate activities_performed is left as "" in fallback context
        assert 'Leave client, donor, activities_performed as ""' in SYSTEM_PROMPT_A1


# ---------------------------------------------------------------------------
# Issue DD — JSON-only output contract (A1)
# ---------------------------------------------------------------------------

class TestSystemPromptA1JsonOnly:
    """A1 prompt must enforce the JSON-only output contract."""

    def test_output_contract_section_present(self):
        assert "Output contract" in SYSTEM_PROMPT_A1

    def test_first_char_rule_present(self):
        assert "FIRST non-whitespace" in SYSTEM_PROMPT_A1

