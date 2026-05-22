"""
Tests for Fix 8 Part 2 — SYSTEM_PROMPT_A4 priority and minimum-output
guarantee instructions.

These tests do NOT call the LLM.  They assert that the required marker phrases
are present in SYSTEM_PROMPT_A4 so that accidental future edits that remove
the priority or minimum-output instructions are caught immediately by the test
suite.
"""

from pipeline.agents.fields_generator import SYSTEM_PROMPT_A4


class TestSystemPromptA4PriorityInstruction:
    """## OUTPUT PRIORITY ORDER section must be present and meaningful."""

    def test_priority_section_heading_present(self):
        assert "OUTPUT PRIORITY ORDER" in SYSTEM_PROMPT_A4

    def test_generated_fields_described_as_highest_priority(self):
        # Checks that the prompt explicitly states generated_fields is first
        assert "generated_fields" in SYSTEM_PROMPT_A4
        assert "highest-priority" in SYSTEM_PROMPT_A4 or "highest priority" in SYSTEM_PROMPT_A4

    def test_priority_order_mentions_part_2_first(self):
        # The ordering section must reference Part 2 before Part 1
        priority_idx = SYSTEM_PROMPT_A4.index("OUTPUT PRIORITY ORDER")
        part2_ref = SYSTEM_PROMPT_A4.find("Part 2", priority_idx)
        part1_ref = SYSTEM_PROMPT_A4.find("Part 1", priority_idx)
        assert part2_ref != -1, "No 'Part 2' reference found after priority heading"
        assert part1_ref != -1, "No 'Part 1' reference found after priority heading"
        assert part2_ref < part1_ref, "Part 2 must appear before Part 1 in the priority order"


class TestSystemPromptA4MinimumOutputGuarantee:
    """Minimum output guarantee section must be present with correct wording."""

    def test_minimum_output_section_heading_present(self):
        assert "Minimum output guarantee" in SYSTEM_PROMPT_A4 or \
               "Minimum output" in SYSTEM_PROMPT_A4

    def test_never_empty_content_instruction_present(self):
        assert "Never return an empty" in SYSTEM_PROMPT_A4 or \
               "never return an empty" in SYSTEM_PROMPT_A4.lower()

    def test_pipeline_halt_consequence_mentioned(self):
        assert "pipeline halt" in SYSTEM_PROMPT_A4.lower() or \
               "halt" in SYSTEM_PROMPT_A4

    def test_at_least_one_entry_per_key_instruction_present(self):
        assert "at least one GeneratedField entry" in SYSTEM_PROMPT_A4 or \
               "at least one" in SYSTEM_PROMPT_A4

    def test_low_confidence_warning_pattern_documented(self):
        assert "Low-confidence" in SYSTEM_PROMPT_A4 or \
               "generation_warnings" in SYSTEM_PROMPT_A4

    def test_no_null_placeholder_instruction_present(self):
        # The prompt must tell the model not to emit null or N/A
        assert "null" in SYSTEM_PROMPT_A4 and "N/A" in SYSTEM_PROMPT_A4


    def test_detailed_tasks_explicitly_mentioned(self):
        """detailed_tasks must be named explicitly in the minimum guarantee section."""
        assert "detailed_tasks" in SYSTEM_PROMPT_A4

    def test_geographic_mismatch_does_not_exempt(self):
        """Prompt must explicitly state geographic/alignment weakness is not an exemption."""
        lower = SYSTEM_PROMPT_A4.lower()
        assert "geographic mismatch" in lower or (
            "geographic" in lower and ("mismatch" in lower or "does not exempt" in lower or "does NOT exempt" in SYSTEM_PROMPT_A4)
        )


class TestSystemPromptA4SourcePreference:
    """R4-C — source-preference section must be present in SYSTEM_PROMPT_A4."""

    def test_source_preference_section_present(self):
        assert "Source preference" in SYSTEM_PROMPT_A4 or \
               "source preference" in SYSTEM_PROMPT_A4.lower()

    def test_condense_instruction_present(self):
        """Prompt must instruct A4 to condense/select from existing KQs."""
        lower = SYSTEM_PROMPT_A4.lower()
        assert "condense" in lower or "select" in lower

    def test_from_scratch_conditions_documented(self):
        """All three from-scratch trigger conditions must appear in the prompt."""
        lower = SYSTEM_PROMPT_A4.lower()
        # Condition 1: KQs empty
        assert "empty" in lower or "[]" in SYSTEM_PROMPT_A4
        # Condition 2: paragraph-style prose
        assert "paragraph" in lower or "prose" in lower
        # Condition 3: misaligned with ToR
        assert "misalign" in lower or "misaligned" in lower or "wrong sector" in lower


# ---------------------------------------------------------------------------
# Issue DD — JSON-only output contract (A4)
# ---------------------------------------------------------------------------

class TestSystemPromptA4JsonOnly:
    """A4 prompt must enforce the JSON-only output contract."""

    def test_output_contract_section_present(self):
        assert "Output contract" in SYSTEM_PROMPT_A4

    def test_first_char_rule_present(self):
        assert "FIRST non-whitespace" in SYSTEM_PROMPT_A4
