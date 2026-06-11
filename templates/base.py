"""
Shared constants and helpers for the donor renderers (GIZ / World Bank).
"""

from __future__ import annotations

# Render-time placeholder for required fields that are empty in the generated
# CV. Applied only inside each renderer's `_build_context` — the artifacts
# (generated_fields.json) keep "" / [], so agent prompts, the A5 empty-field
# check, and A7 field edits are unaffected. The set of fields that receive this
# placeholder is kept aligned with REQUIRED_FIELDS_BY_DONOR in
# pipeline/agents/content_reviewer.py.
NOT_FOUND_PLACEHOLDER = "[Not found in source CV]"


def placeholder_if_empty(value: str) -> str:
    """Return the value, or NOT_FOUND_PLACEHOLDER when it is empty/whitespace."""
    return value if (value and value.strip()) else NOT_FOUND_PLACEHOLDER


def other_skills_text(value) -> str:
    """other_skills is free text (str). The renderers read raw artifact JSON,
    so coerce a legacy list (from a pre-change completed run being re-rendered)
    into a '; '-joined string defensively — mirrors the CVData field validator."""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(s).strip() for s in value if str(s).strip())
    return (value or "").strip()
