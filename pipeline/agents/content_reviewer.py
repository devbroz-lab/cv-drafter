"""
Agent 5 — Content Reviewer.

Reviews generated CVData for factual inconsistencies, unverifiable claims, and
style issues.  Fixes low-severity issues automatically.  Flags high-severity
issues and marks the pipeline as 'blocked' — requiring human resolution before
proceeding to Agent 6.

Input:  runs/{session_id}/generated_fields.json + tor_data.json
Output: updates generated_fields.json (adds "review" block, sets "generated" to reviewed data)
"""

from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

from models import CVData
from pipeline.manifest import update_step
from pipeline.utils import resolve_tor_for_agents, strip_code_fences

client = Anthropic()

SYSTEM_PROMPT = """
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
        "recommendation": "..."
      }
    ],
    "low_severity": [
      {
        "path": "...dot-path into CVData...",
        "field": "...",
        "issue": "...",
        "original": "...",
        "fixed": "..."
      }
    ],
    "passed": true
  }
}

- `passed` is true only if `high_severity` is empty.
- If `passed` is false, the pipeline will be blocked until a human resolves
  the flagged issues.
- `path` must be a machine-readable dot-path into CVData for each issue.
  Examples:
  - "countries_of_experience.0.country"
  - "generated_fields.2.content"
  - "relevant_projects.1.activities_performed"
- `field` remains a human-readable label for UI display only.
- If an issue refers to multiple fields, split it into separate issue objects
  so each one has exactly one concrete `path`.

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

3. Exceeds 25-word limit
   A generated_fields bullet exceeds 25 words.
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
  of unverifiable claims.
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

### All other fields
- Check for filler language only.
- Do not flag style, length, or completeness unless the field is in
  generated_fields.

## What NOT to do
- Do not rewrite content that is already good — if a bullet is clear,
  grounded, and active, leave it unchanged.
- Do not flag subjective style preferences as issues.
- Do not change field values outside of the fixes described above.

## Inputs
The user message will contain:
  <cv_data>             — generated CVData from generated_fields.json    </cv_data>
  <tor_data>            — DistilledToR from tor_data.json                </tor_data>
  <generation_warnings> — warnings list from Agent 4                     </generation_warnings>
"""

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
    gf_raw = json.loads(gf_path.read_text(encoding="utf-8"))

    cv_data_in = gf_raw["generated"]
    generation_warns = gf_raw.get("generation_warnings", [])
    tor_raw = json.loads((run_dir / "tor_data.json").read_text(encoding="utf-8"))
    tor_data = resolve_tor_for_agents(tor_raw, context="content_reviewer.run")

    user_message = (
        f"<cv_data>\n{json.dumps(cv_data_in, indent=2)}\n</cv_data>\n\n"
        f"<tor_data>\n{json.dumps(tor_data, indent=2)}\n</tor_data>\n\n"
        f"<generation_warnings>\n{json.dumps(generation_warns, indent=2)}\n</generation_warnings>"
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    if response.stop_reason == "max_tokens":
        update_step(run_dir, "content_reviewer", "failed")
        raise ValueError("Content Reviewer response truncated (max_tokens reached).")

    raw = strip_code_fences(response.content[0].text.strip())

    try:
        parsed = json.loads(raw)
        cv_data_out = CVData.model_validate(parsed["data"])
        review = parsed["review"]
        passed = review.get("passed", False)
        assert "high_severity" in review
        assert "low_severity" in review
    except Exception as exc:
        update_step(run_dir, "content_reviewer", "failed")
        raise ValueError(f"Content Reviewer returned invalid output: {exc}\n\nRaw:\n{raw}") from exc

    # Restore any generated_fields content that the reviewer inadvertently emptied
    original_gf = cv_data_in.get("generated_fields", [])
    reviewed_gf = parsed["data"].get("generated_fields", [])
    for i, (orig, reviewed) in enumerate(zip(original_gf, reviewed_gf, strict=False)):
        if orig.get("content", "").strip() and not reviewed.get("content", "").strip():
            reviewed["content"] = orig["content"]
            parsed["data"]["generated_fields"][i] = reviewed

    # Re-validate after restoration
    cv_data_out = CVData.model_validate(parsed["data"])

    gf_raw["generated"] = cv_data_out.model_dump()
    gf_raw["review"] = review
    gf_path.write_text(json.dumps(gf_raw, indent=2, ensure_ascii=False), encoding="utf-8")

    if not passed:
        update_step(run_dir, "content_reviewer", "blocked")
    else:
        update_step(run_dir, "content_reviewer", "done")

    return cv_data_out, passed
