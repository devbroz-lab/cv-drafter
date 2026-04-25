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
from pipeline.utils import strip_code_fences

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
        "field": "...",
        "issue": "...",
        "recommendation": "..."
      }
    ],
    "low_severity": [
      {
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

## Severity definitions

### High severity — flag only, do NOT fix
Flag as high severity if:
1. Factual inconsistency — a field contradicts another field in the same CVData.
2. Unverifiable claim — a generated_fields item makes a specific, concrete claim
   (number, named technology, named institution) that cannot be traced to any
   project or qualification in the CVData.
3. Missing critical ToR requirement — a required_competency or key_task is not
   addressed by any field in the CVData at all.

CRITICAL: When flagging high severity, copy the field value UNCHANGED into the
output CVData. Never empty or nullify a field you are flagging.

### Low severity — fix automatically
Fix as low severity if:
1. Filler or passive language in generated fields.
2. Missing action verb at the start of a generated bullet.
3. Generated bullet exceeds 25 words — tighten without losing the core claim.
4. Generic language with no specificity in generated fields.
5. Whitespace or formatting inconsistency.

## Review scope
- Focus on generated_fields items (source="tor" items especially).
- Check relevant_projects for date consistency and filler language only.
- Do NOT rewrite project content for style beyond filler removal.

## What NOT to do
- Do not flag subjective style preferences.
- Do not change field values outside the fixes described above.

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
    tor_data = json.loads((run_dir / "tor_data.json").read_text(encoding="utf-8"))["data"]

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
