"""
Agent 5 — Content Reviewer.

Reviews generated CVData for factual inconsistencies, unverifiable claims, and
style issues.  Fixes low-severity issues automatically.  Flags high-severity
issues and marks the pipeline as 'blocked' — requiring human resolution before
proceeding to Agent 6.

Post-processing (Python, deterministic — applied AFTER LLM review):
  - Forces passed=false whenever high_severity is non-empty (Issue 5.1)
  - Injects a high_severity finding when energy-sector experience years gap
    exceeds threshold for Team Lead / leadership tier roles (Issue 5.10)
  - Strips trivial word-count flags within WORD_COUNT_TOLERANCE_PCT (Issue 5.4)

Solvability tagging:
  - Every finding (high and low severity) carries a "solvability" field.
  - "pipeline": the field_editor agent can resolve this via a scalar rewrite.
  - "human": requires recruiter judgement or information outside the pipeline.

Input:  runs/{session_id}/generated_fields.json + tor_data.json + mapped_cv.json
Output: updates generated_fields.json (adds "review" block, sets "generated" to reviewed data)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from anthropic import Anthropic

from models import CVData
from pipeline.config import (
    ANTHROPIC_MAX_TOKENS,
    ANTHROPIC_MODEL,
    EXPERIENCE_GAP_BLOCK_THRESHOLD_YEARS,
    WORD_COUNT_TOLERANCE_PCT,
)
from pipeline.manifest import update_step
from pipeline.text_encoding import UTF_8
from pipeline.utils import (
    load_json_file,
    load_tor_envelope,
    parse_json_string,
    resolve_selected_tor_pool,
)
from pipeline.validation import (
    cross_reference_geo_alternative,
    extract_required_years_for_tier,
    extract_role_tier,
    total_documented_years,
)

client = Anthropic()

SYSTEM_PROMPT_A5 = """
CRITICAL OUTPUT RULE: Your entire response must be a single valid JSON object.
Output the opening brace { immediately as the very first character.
Do not write any text before the JSON — no observations, no reasoning,
no analysis, no key observations, no preamble of any kind.
No markdown fences. The response must be parseable by json.loads() with no
pre-processing.

You are the Content Reviewer agent in a document processing pipeline. You
receive a fully generated CVData object, the original DistilledToR, and a
list of generation warnings from the previous agent. Your job is to review
every populated field in the CVData, fix low-severity issues automatically,
and flag high-severity issues for human resolution.

## Output rules
- Respond with a single JSON object and nothing else.
- No preamble, no explanation, no markdown fences.
- The output must have this exact shape:

{
  "data": { ...full CVData object, with low-severity fixes applied... },
  "review": {
    "high_severity": [
      {
        "path": "...dot-path into CVData...",
        "field": "...",
        "issue": "...",
        "recommendation": "...",
        "solvability": "pipeline" | "human"
      }
    ],
    "low_severity": [
      {
        "path": "...dot-path into CVData...",
        "field": "...",
        "issue": "...",
        "original": "...",
        "fixed": "...",
        "solvability": "pipeline" | "human"
      }
    ],
    "passed": true
  }
}

## BLOCKING RULE — mandatory
`passed` MUST be false if `high_severity` contains ANY entries.
Setting `passed: true` when high_severity is non-empty is an error.
Python post-processing will override any incorrect value — but always
set it correctly yourself.

## Solvability tagging — mandatory on every finding
Every entry in high_severity and low_severity MUST include a "solvability" field.
Use exactly one of two string values:

  "pipeline" — The field_editor agent can resolve this by rewriting a scalar
               field value. The fix requires no external information, no
               recruiter judgement, and no data that isn't already in the CV.
               Examples: correcting a date, fixing a location string, rewriting
               a passive bullet, tightening an overlong field.

  "human"    — Resolution requires recruiter judgement or information that
               exists outside the pipeline. The field_editor cannot fix this
               by rewriting text alone.
               Examples: a claim that may be true but cannot be verified from
               the CV data, a missing competency that the candidate may or may
               not actually have, a language proficiency that needs candidate
               confirmation.

Solvability assignment rules by issue type:

  Factual inconsistency (date errors, location mismatches)  → "pipeline"
  Unverifiable claim (specific figure or credential)        → "human"
  Missing critical ToR requirement                          → "human"
  Filler / passive language                                 → "pipeline"
  Missing action verb                                       → "pipeline"
  Exceeds word limit                                        → "pipeline"
  Generic language with no specificity                      → "pipeline"
  Whitespace / formatting                                   → "pipeline"
  Language proficiency gap or inconsistency                 → "human"
  Geographic requirement gap                                → "human"

When in doubt: if the fix requires only rewriting existing text using
information already present in the CVData, use "pipeline". If it requires
a human to verify, supply, or decide something, use "human".

## Severity definitions

### High severity — flag only, do NOT fix
Flag as high severity if any of the following are true:

1. Factual inconsistency
   A field contains a claim that contradicts another field in the same CVData.
   Examples:
   - A date_from is later than date_to in the same record.
   - A project location contradicts the expert's stated countries_of_experience.
   - present_position describes a role not found anywhere in relevant_projects.

2. Unverifiable claim
   A generated_fields item (source="tor" or source="generated") makes a
   specific, concrete claim — a number, a named technology, a named
   institution — that cannot be traced to any project or qualification
   in the CVData.
   When verifying a generated_fields bullet against CV evidence, check BOTH
   activities_performed AND main_project_features for each project.
   activities_performed is frequently empty — this does not mean the project
   lacks evidence. A claim is only unverifiable if it cannot be traced to
   either field across all projects.
   Examples:
   - "Managed a $4M grid rehabilitation project" — no project in CVData
     mentions this figure.
   - "Certified PRINCE2 practitioner" — no certification listed.
   Do NOT flag vague or qualitative claims — only specific, concrete,
   traceable ones.

3. Missing critical ToR requirement
   A required_competency or key_task from the DistilledToR is not addressed
   by any field in the CVData — not in generated_fields, not in any project's
   activities_performed, not in key_qualifications.
   Only flag if the gap is total — if there is partial evidence, treat it
   as low severity.

CRITICAL: When flagging a field as high severity, copy its current value
into the output CVData UNCHANGED. Never empty, clear, or nullify a field
you are flagging. The flag is for human awareness only — the original
content must survive into the output intact.

## WB FORMAT RULE — source='tor' tasks are correct and expected
For World Bank format CVs, detailed_tasks with source='tor' are EXPECTED
and CORRECT. They describe what the consultant WILL DO in the proposed role.
They are prospective role descriptions, NOT claims about past experience.

DO NOT block or flag detailed_tasks for being ToR-sourced.
DO NOT flag detailed_tasks as "unverifiable" simply because they describe
future responsibilities rather than past work.

Only flag a detailed_task if it:
(a) Contains a factual error that contradicts the candidate's CV data, OR
(b) Claims a specific past accomplishment (e.g. "Led BADGE project in 2022")
    that cannot be verified against relevant_projects.

## Geographic requirement
Flag as high severity if the candidate does not meet geographic requirements
stated in the DistilledToR. Assign solvability "human" — only a recruiter
can verify whether the candidate qualifies via alternative pathways or
additional undocumented experience.

## Language proficiency
Before flagging a language proficiency rating as high severity, check the
candidate's education entries for degrees in that language and other_skills
for language courses or certificates. Flag as high severity with solvability
"human" — proficiency confirmation requires the candidate or recruiter.

## Leadership language — severity calibration
For roles with titles containing any of: Lead, Leader, Manager, Director,
Head, Chief, Deputy, VP, President:
- "Led", "Directed", "Managed", "Coordinated", "Guided", "Oversaw" are
  APPROPRIATE and must NOT be flagged as high severity.
- "Contributed to", "Supported", "Assisted" are appropriate for junior roles
  but are WEAK for leadership roles — suggest stronger verbs as low severity
  with solvability "pipeline".

For roles with titles containing: Analyst, Associate, Coordinator, Member,
Junior, Assistant:
- "Led", "Directed", "Managed" MAY be flagged if the claim appears to
  overstate solo responsibility vs. team contribution.
- Only flag if the specific claim scope does not match the title scope.

## Severity definitions

### Low severity — fix automatically
Fix as low severity if any of the following are true:

1. Filler or passive language
   A generated field contains: "responsible for", "involved in",
   "participated in", "assisted with", "worked on", "helped to",
   "supported the", or any passive construction.
   Fix: rewrite with an active verb grounded in the same content.

2. Missing action verb
   A generated_fields bullet or key_qualifications item does not begin
   with an action verb.
   Fix: prepend or restructure to lead with an action verb.

3. Exceeds word limit
   A generated_fields bullet exceeds the word limit by more than 10%.
   NOTE: A 25-word limit allows up to 27 words (10% tolerance) — do NOT
   flag bullets at 26 or 27 words when the limit is 25.
   Fix: tighten without losing the core claim. Do not remove sector keywords.

4. Generic language with no specificity
   A generated_fields bullet contains no concrete noun, no measurable
   outcome, and no sector keyword — it could apply to any expert in
   any field.
   Fix: inject the most relevant sector keyword from DistilledToR.sector_keywords
   that is naturally applicable. If none apply, flag as high severity instead.

5. Whitespace or formatting inconsistency
   Trailing spaces, double spaces, inconsistent capitalisation within
   a list, or punctuation at the end of some bullets but not others.
   Fix: normalise silently. Do not list these in low_severity unless
   the change affects meaning.

## Review scope

### generated_fields
- Review every GeneratedField item for all severity rules above.
- Pay extra attention to items with source="tor" — they are most at risk
  of unverifiable claims. But see the WB FORMAT RULE above: for WB CVs,
  source='tor' tasks are expected and should only be flagged for actual
  factual contradictions with CV data.
- Cross-reference generation_warnings from Agent 4 — if a warning flags
  weak CV grounding, scrutinise those bullets first.
- When checking whether a bullet is verifiable against CV evidence, use ALL
  of the following fields as valid evidence sources:
    - relevant_projects: main_project_features, positions_held, project_name,
      location, client, company, donor
    - key_qualifications (extracted list)
    - certifications
    - membership_professional_bodies

Do NOT require activities_performed to be populated — it is intentionally
left empty in the extraction stage for GIZ CVs. A bullet is only
unverifiable if no evidence exists across ALL of the above fields combined.

### relevant_projects
- Review activities_performed and main_project_features for filler language
  (low severity only — do not rewrite project content beyond filler removal).
- Review date consistency: date_from must be earlier than date_to.
- Do NOT rewrite project content for style — only fix filler and date errors.

### personal_info
- Check that date_of_birth, nationality, and place_of_residence are
  internally consistent where cross-checkable.
- Do not flag missing optional fields as issues.

### education
- Check date consistency only (date_from earlier than date_to).
- Do not flag content.

### languages
- Check that reading_raw, speaking_raw, writing_raw are populated for
  every language entry. If any are empty, flag as high severity only if
  the language appears in DistilledToR.language_requirements.
- Before flagging a language as a high severity gap, check the candidate's
  education entries and other_skills for evidence of proficiency.

### All other fields
- Check for filler language only.
- Do not flag style, length, or completeness unless the field is in
  generated_fields.

## What NOT to do
- Do not rewrite content that is already good — if a bullet is clear,
  grounded, and active, leave it unchanged.
- Do not flag subjective style preferences as issues.
- Do not change field values outside of the fixes described above.
- Do not flag detailed_tasks with source='tor' in World Bank CVs as
  unverifiable claims — they are prospective role task descriptions.

## Pre-computed context
The `<pre_computed>` block in your input contains the following Python-computed
values.  Use them as described — do NOT independently recalculate them.

### Fields and how to use them

`donor` (str)
  The donor format: "giz" or "world_bank".  Use to apply format-specific rules
  (e.g. WB FORMAT RULE for source='tor' tasks).

`proposed_position` (str)
  The position title from the pipeline params (not extracted from the CV).

`tier` (str — "team_lead", "expert", or "")
  The heuristic role tier derived from proposed_position and category.
  Use to calibrate leadership-language expectations:
  - "team_lead": strong leadership verbs ("Led", "Directed", "Managed") are
    appropriate and should NOT be flagged.  Passive or junior verbs
    ("supported", "assisted") are weak — flag as low severity.
  - "expert": individual-contributor framing is correct.

`required_experience_years` (int)
  Minimum years of sector experience the ToR requires for this tier.
  Derived from the ToR text; falls back to tier defaults (team_lead=10, expert=5).

`documented_total_years` (float)
  Total documented years across ALL relevant_projects (overlapping roles not
  de-duplicated — this is a conservative lower bound).

`documented_energy_years` (float)
  Total documented years in energy/electricity-sector projects only.
  This is the value compared against `required_experience_years`.

`experience_gap_years` (float)
  = max(0, required_experience_years − documented_energy_years).
  A value > 0 means the candidate may fall short of the sector requirement.

  If `experience_gap_years > 0` AND `tier == "team_lead"`:
    - Acknowledge that a gap exists.
    - Do NOT independently calculate or re-flag the gap as a separate finding —
      Python post-processing will inject a standardised high_severity finding
      automatically.  Producing your own gap finding risks duplication or
      conflicting wording.
    - Use the gap magnitude to calibrate how strictly you apply geographic
      and competency checks: a large gap warrants stricter scrutiny of whether
      the candidate's non-energy experience genuinely covers ToR competencies.

`geographic_alternative` (dict)
  Contains:
    required_regions   : list[str] — geographic requirements from the ToR
    candidate_countries: list[str] — candidate's documented countries
    direct_match       : bool      — whether any overlap exists
    notes              : str       — human-readable summary

  Use to inform the geographic gap check:
  - If `direct_match` is true, the candidate has documented experience in a
    required country — do NOT flag as a geographic gap.
  - If `direct_match` is false AND `required_regions` is non-empty, flag as
    high severity with solvability "human" (only a recruiter can confirm
    alternative pathways).
  - If `required_regions` is empty, no geographic requirement was found in the
    ToR — do not flag a geographic gap.

## Auto-fix note
Low-severity issues are fixed inline in the `data` block before the review is
finalised.  These fixes are applied exactly once and are not re-reviewed.
Therefore:
- Prefer the minimal rewrite that resolves the flagged issue.
- Never introduce new claims, expand the scope of a statement, or change
  meaning beyond what is necessary to fix the specific problem.
- If you are uncertain whether a fix would introduce new content, prefer
  flagging as high severity with solvability "human" instead.

## Inputs
The user message will contain:
  <cv_data>             — generated CVData from generated_fields.json    </cv_data>
  <tor_data>            — DistilledToR from tor_data.json                </tor_data>
  <generation_warnings> — warnings list from Agent 4                     </generation_warnings>
  <pre_computed>        — pre-computed values from Python (experience gap,
                          geographic pathway, format info)               </pre_computed>
"""


# ---------------------------------------------------------------------------
# Pre-computation helpers (called before LLM, injected into user message)
# ---------------------------------------------------------------------------


def _precompute_context(
    cv_data_in: dict,
    tor_data: dict,
    params: dict,
) -> dict:
    """
    Compute deterministic facts that should be surfaced to the LLM reviewer
    to prevent it from missing obvious qualification gaps.

    Returns a dict that is serialised into the <pre_computed> tag.
    """
    proposed_position = cv_data_in.get("proposed_position", "") or params.get("proposed_position", "")
    category = cv_data_in.get("category", "") or params.get("category", "")
    donor = params.get("donor", "giz")

    projects = cv_data_in.get("relevant_projects", [])
    countries = [c.get("country", "") for c in cv_data_in.get("countries_of_experience", [])]

    # Experience-years computation
    tier = extract_role_tier(proposed_position, category)
    required_years = extract_required_years_for_tier(tor_data, proposed_position, category)
    documented_total = total_documented_years(projects, energy_only=False)
    documented_energy = total_documented_years(projects, energy_only=True)

    experience_gap = max(0.0, required_years - documented_energy)

    # Geographic alternative pathway (kept for LLM context only)
    geo_alt = cross_reference_geo_alternative(tor_data, countries)

    result = {
        "donor": donor,
        "proposed_position": proposed_position,
        "tier": tier,
        "required_experience_years": required_years,
        "documented_total_years": round(documented_total, 1),
        "documented_energy_years": round(documented_energy, 1),
        "experience_gap_years": round(experience_gap, 1),
        "geographic_alternative": geo_alt,
    }
    return result


# ---------------------------------------------------------------------------
# Post-processing helpers (applied after LLM response)
# ---------------------------------------------------------------------------


def _enforce_passed_field(review: dict) -> None:
    """
    P0 fix (Issue 5.1): Force passed=false whenever high_severity is non-empty.
    Mutates review in-place.
    """
    if review.get("high_severity"):
        review["passed"] = False


def _inject_experience_gap_finding(
    review: dict,
    pre_computed: dict,
) -> list[dict]:
    """
    P0 fix (Issue 5.10): If the candidate has an energy-sector experience gap
    of >= EXPERIENCE_GAP_BLOCK_THRESHOLD_YEARS for a team_lead tier role,
    and the reviewer has NOT already surfaced this, inject a high_severity entry.
    Returns list of injected entries (for audit).
    """
    tier = pre_computed.get("tier", "")
    gap = pre_computed.get("experience_gap_years", 0.0)
    required = pre_computed.get("required_experience_years", 0)
    documented = pre_computed.get("documented_energy_years", 0.0)
    position = pre_computed.get("proposed_position", "")

    if tier != "team_lead":
        return []
    if gap < EXPERIENCE_GAP_BLOCK_THRESHOLD_YEARS:
        return []

    # Check if reviewer already raised this
    existing_text = " ".join(
        e.get("issue", "") for e in review.get("high_severity", [])
    ).lower()
    already_flagged = any(
        kw in existing_text
        for kw in ("experience gap", "years of experience", "electricity sector experience",
                   "energy sector experience", f"{int(required)} year")
    )
    if already_flagged:
        return []

    finding = {
        "path": "relevant_projects",
        "field": "Experience years (electricity sector)",
        "issue": (
            f"Team Lead / leadership tier requires {required} years of electricity-sector "
            f"experience. CV documents approximately {documented:.1f} years in energy/electricity "
            f"sector — a gap of {gap:.1f}+ years. Pre-energy-sector roles (microfinance, "
            "construction management, economic development, humanitarian) do not count toward "
            "this requirement."
        ),
        "recommendation": (
            "Human review required: verify whether any additional energy-sector experience "
            "exists outside current relevant_projects. If the gap is confirmed, this "
            "candidate does not meet the Team Lead experience threshold."
        ),
        "solvability": "human",
        "_injected_by_postprocessing": True,
    }
    review.setdefault("high_severity", []).append(finding)
    review["passed"] = False
    return [finding]


def _filter_word_count_pedantry(review: dict) -> list[dict]:
    """
    P2 fix (Issue 5.4): Remove low_severity word-count entries within
    WORD_COUNT_TOLERANCE_PCT of the limit.
    Returns list of removed entries.
    """
    word_limit_pattern = re.compile(r"(\d+)\s*word", re.IGNORECASE)
    removed: list[dict] = []
    kept_low: list[dict] = []

    for entry in review.get("low_severity", []):
        issue = entry.get("issue", "").lower()
        if "word" in issue and ("exceed" in issue or "limit" in issue or "over" in issue):
            numbers = word_limit_pattern.findall(issue)
            if len(numbers) >= 2:
                try:
                    actual = int(numbers[0])
                    limit = int(numbers[1])
                except (ValueError, IndexError):
                    kept_low.append(entry)
                    continue
                max_acceptable = int(limit * (1 + WORD_COUNT_TOLERANCE_PCT))
                if actual <= max_acceptable:
                    entry["_removed_reason"] = (
                        f"Word count {actual} is within {WORD_COUNT_TOLERANCE_PCT*100:.0f}% "
                        f"tolerance of limit {limit} (max acceptable: {max_acceptable})."
                    )
                    removed.append(entry)
                    continue
        kept_low.append(entry)

    review["low_severity"] = kept_low
    return removed


def _apply_post_processing(
    review: dict,
    pre_computed: dict,
) -> dict:
    """
    Apply all deterministic post-processing rules to the review dict.
    Returns an audit dict logging all injections and removals.
    """
    audit: dict[str, list] = {
        "experience_gap_injections": [],
        "word_count_removals": [],
    }

    # P0: Inject experience gap if missing
    audit["experience_gap_injections"] = _inject_experience_gap_finding(review, pre_computed)

    # P2: Word count tolerance
    audit["word_count_removals"] = _filter_word_count_pedantry(review)

    # P0 (always last): Enforce passed=false if any high_severity remain
    _enforce_passed_field(review)

    review["demoted"] = audit
    return audit


# ---------------------------------------------------------------------------
# JSON extraction helper (defence against leading prose in LLM output)
# ---------------------------------------------------------------------------


def _extract_json_from_text(text: str) -> str:
    """
    Extract a JSON object from text that may have leading or trailing prose.

    When the model emits reasoning or observations before the JSON object,
    json.loads() fails at character 0.  This function finds the outermost
    { ... } span and returns it, letting parse_json_string work on clean JSON.

    If no braces are found, returns the original text so that parse_json_string
    can produce a clean error message rather than a confusing index error.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text  # let downstream raise with the original text
    return text[start : end + 1]


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(run_dir: Path) -> tuple[CVData, bool]:
    """
    Review the generated CVData and write the review block back to
    generated_fields.json.

    Returns:
        (reviewed_cv_data, passed) — if passed is False, the pipeline is
        blocked and the session status must be set to 'reviewer_blocked'.
    """
    update_step(run_dir, "content_reviewer", "running")

    gf_path = run_dir / "generated_fields.json"
    gf_raw = load_json_file(
        gf_path,
        context="content_reviewer.generated_fields",
        required_keys=("generated",),
    )

    cv_data_in = gf_raw["generated"]
    generation_warns = gf_raw.get("generation_warnings", [])
    tor_wrap = load_tor_envelope(
        run_dir / "tor_data.json",
        context="content_reviewer.tor_data",
    )
    tor_data = resolve_selected_tor_pool(tor_wrap, context="content_reviewer.tor_data")

    # Load manifest for params (needed for pre-computation)
    manifest_path = run_dir / "manifest.json"
    params: dict = {}
    if manifest_path.exists():
        try:
            manifest = load_json_file(
                manifest_path,
                context="content_reviewer.manifest",
                required_keys=None,
            )
            params = manifest.get("params", {})
        except Exception:
            pass

    # Pre-compute experience gap and geographic alternative
    pre_computed = _precompute_context(cv_data_in, tor_data, params)

    user_message = (
        f"<cv_data>\n{json.dumps(cv_data_in, indent=2)}\n</cv_data>\n\n"
        f"<tor_data>\n{json.dumps(tor_data, indent=2)}\n</tor_data>\n\n"
        f"<generation_warnings>\n{json.dumps(generation_warns, indent=2)}\n</generation_warnings>\n\n"
        f"<pre_computed>\n{json.dumps(pre_computed, indent=2)}\n</pre_computed>"
    )

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=ANTHROPIC_MAX_TOKENS,
        system=SYSTEM_PROMPT_A5,
        messages=[{"role": "user", "content": user_message}],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "content_reviewer", "failed")
        raise ValueError("Content Reviewer response truncated (max_tokens reached).")

    raw_text = response.content[0].text.strip()
    raw_text = _extract_json_from_text(raw_text)

    try:
        parsed = parse_json_string(raw_text, context="content_reviewer.llm_response")
        cv_data_out = CVData.model_validate(parsed["data"])
        review = parsed["review"]
        assert "high_severity" in review
        assert "low_severity" in review
    except Exception as exc:
        update_step(run_dir, "content_reviewer", "failed")
        raise ValueError(
            f"Content Reviewer returned invalid output: {exc}\n\nRaw:\n{raw_text}"
        ) from exc

    # Restore any generated_fields content that the reviewer inadvertently emptied
    original_gf = cv_data_in.get("generated_fields", [])
    reviewed_gf = parsed["data"].get("generated_fields", [])
    for i, (orig, reviewed_item) in enumerate(zip(original_gf, reviewed_gf, strict=False)):
        if orig.get("content", "").strip() and not reviewed_item.get("content", "").strip():
            reviewed_item["content"] = orig["content"]
            parsed["data"]["generated_fields"][i] = reviewed_item

    # Re-validate after restoration
    cv_data_out = CVData.model_validate(parsed["data"])

    # Apply all deterministic post-processing
    _apply_post_processing(review, pre_computed)

    passed = review.get("passed", False)

    gf_raw["generated"] = cv_data_out.model_dump()
    gf_raw["review"] = review
    gf_path.write_text(json.dumps(gf_raw, indent=2, ensure_ascii=False), encoding=UTF_8)

    if not passed:
        update_step(run_dir, "content_reviewer", "blocked")
    else:
        update_step(run_dir, "content_reviewer", "done")

    return cv_data_out, passed
