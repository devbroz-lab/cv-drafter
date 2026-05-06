# Content Reviewer — Solvability Update: Migration Guide

## What Changed and Why

The content reviewer has been updated with two changes:

1. **Solvability tagging** — every finding now carries a `"solvability"` field (`"pipeline"` or `"human"`) so downstream consumers know whether the field_editor agent can address an issue or whether it requires recruiter intervention.

2. **Post-processing demotions removed** — four demotion functions that silently moved issues from high → low severity have been deleted. Issues now stay at whatever severity the LLM assigns. This makes the review output honest and predictable.

---

## Removed Code

The following four functions have been deleted from `content_reviewer.py`. Any references to them elsewhere in the codebase must be removed or replaced:

| Removed function | What it did |
|---|---|
| `_filter_wb_tor_source_blocks` | Removed high-severity entries that flagged WB `source='tor'` tasks as unverifiable |
| `_downgrade_geographic_blocks` | Moved geographic high-severity findings to low-severity when OR-alternative pathway was satisfied |
| `_downgrade_language_blocks_with_evidence` | Moved language high-severity findings to low-severity when education/skills showed contradicting evidence |
| `_filter_leadership_verb_blocks` | Moved leadership-verb high-severity findings to low-severity for leadership-titled roles |

The `review.demoted` audit key still exists in the output but now only contains two sub-keys: `experience_gap_injections` and `word_count_removals`. Any frontend or API logic that reads `demoted.wb_tor_source_demotions`, `demoted.geographic_demotions`, `demoted.language_demotions`, or `demoted.leadership_verb_demotions` will receive `undefined` / `KeyError` and must be updated.

---

## Removed Imports

The following imports were removed from `content_reviewer.py` because they were only used by the deleted demotion functions:

```python
# REMOVED — delete from content_reviewer.py if still present
from pipeline.config import (
    LEADERSHIP_TITLE_TOKENS,       # was used by _filter_leadership_verb_blocks
    LEADERSHIP_VERBS_ALLOWED,      # was used by _filter_leadership_verb_blocks
)
from pipeline.validation import (
    language_evidence_in_education,  # was used by _downgrade_language_blocks_with_evidence
)
```

`cross_reference_geo_alternative` is still imported — it is still called inside `_precompute_context` to provide geographic context to the LLM via the `<pre_computed>` tag. Do not remove it.

Check `pipeline/config.py` and `pipeline/validation.py` — if `LEADERSHIP_TITLE_TOKENS`, `LEADERSHIP_VERBS_ALLOWED`, and `language_evidence_in_education` are not used anywhere else, they can be removed from those modules too. If they are used elsewhere, leave them.

---

## New Data Shape

### `high_severity` items

Every item now has a `"solvability"` field. Old shape:

```json
{
  "path": "relevant_projects[2].date_from",
  "field": "Date consistency",
  "issue": "date_from 2019 is later than date_to 2017",
  "recommendation": "Correct date_from to 2015"
}
```

New shape:

```json
{
  "path": "relevant_projects[2].date_from",
  "field": "Date consistency",
  "issue": "date_from 2019 is later than date_to 2017",
  "recommendation": "Correct date_from to 2015",
  "solvability": "pipeline"
}
```

### `low_severity` items

Same addition. Old shape:

```json
{
  "path": "generated_fields[0].content",
  "field": "Filler language",
  "issue": "Contains 'responsible for'",
  "original": "Was responsible for managing grid inspections",
  "fixed": "Managed grid inspections across 3 provinces"
}
```

New shape:

```json
{
  "path": "generated_fields[0].content",
  "field": "Filler language",
  "issue": "Contains 'responsible for'",
  "original": "Was responsible for managing grid inspections",
  "fixed": "Managed grid inspections across 3 provinces",
  "solvability": "pipeline"
}
```

### Post-processing injected finding

The experience gap finding injected by `_inject_experience_gap_finding` now also carries `"solvability": "human"` and an `"_injected_by_postprocessing": true` flag. No change needed here unless you were filtering on the absence of solvability.

### `review.demoted`

Old shape had four keys:

```json
{
  "demoted": {
    "wb_tor_source_demotions": [...],
    "experience_gap_injections": [...],
    "geographic_demotions": [...],
    "language_demotions": [...],
    "leadership_verb_demotions": [...],
    "word_count_removals": [...]
  }
}
```

New shape has two keys only:

```json
{
  "demoted": {
    "experience_gap_injections": [...],
    "word_count_removals": [...]
  }
}
```

---

## Files to Update

### 1. `api/routers/sessions.py` — `GET /sessions/{id}/review`

This endpoint serialises the review block from `generated_fields.json` and returns it to the client. The response model or serialisation logic may need updating to:

- Include `solvability` in the serialised finding objects. If you are using a Pydantic response model for findings, add the field there.
- Stop referencing `demoted.wb_tor_source_demotions`, `demoted.geographic_demotions`, `demoted.language_demotions`, `demoted.leadership_verb_demotions` — these keys no longer exist.

If the endpoint passes the raw `review` dict through without a Pydantic model, no structural change is needed — the new fields will be included automatically. Verify that the frontend consuming this endpoint handles the new `solvability` field correctly.

### 2. `api/models/requests.py` or response models

If you have Pydantic models for `HighSeverityFinding` or `LowSeverityFinding`, add:

```python
solvability: Literal["pipeline", "human"]
```

If these models are used for validation of the reviewer's output inside `content_reviewer.py` itself (they are not currently — the code uses raw dict access), add the field there too.

### 3. `pipeline/config.py`

Check whether `LEADERSHIP_TITLE_TOKENS` and `LEADERSHIP_VERBS_ALLOWED` are used anywhere outside `content_reviewer.py`. If they are only used there, remove them from `config.py`. If unsure, leave them and clean up later.

### 4. `pipeline/validation.py`

Check whether `language_evidence_in_education` is used anywhere outside `content_reviewer.py`. If it is only used there, remove it from `validation.py`. If unsure, leave it.

### 5. Frontend / client consuming `GET /sessions/{id}/review`

The review payload now includes `solvability` on every finding. Recommended use:

- For `high_severity` findings with `solvability: "pipeline"`: surface a prompt or button directing the user to the `POST /field-edit` endpoint with a suggested `field_path` drawn from the finding's `path` field.
- For `high_severity` findings with `solvability: "human"`: surface a plain advisory message. The `POST /resolve` endpoint with `force_pass: true` or an `overrides` dict is the relevant action here.
- For `low_severity` findings: these are already auto-fixed. Solvability is informational only — useful if you want to show a "what was auto-corrected" log.

### 6. `POST /sessions/{id}/field-edit` handler (optional guardrail)

You may optionally add a guardrail that rejects `field-edit` instructions targeting issues whose `solvability` is `"human"`. To do this:

- Load `generated_fields.json` and read `review.high_severity`.
- For each incoming edit, check whether its `field_path` matches the `path` of any high-severity finding with `solvability: "human"`.
- If so, return a `422` with a message explaining the issue requires human resolution, not a field edit.

This is optional — the field_editor agent will likely just produce a stylistically clean but factually unchanged result for such edits, so no data will be corrupted if you skip the guardrail.

---

## Solvability Reference Table

| Issue type | Severity | Solvability | Notes |
|---|---|---|---|
| Date inconsistency (date_from > date_to) | high | `pipeline` | field_editor corrects the scalar date string |
| Location contradicts countries_of_experience | high | `pipeline` | field_editor corrects the location or countries string |
| Unverifiable specific claim (figure, credential) | high | `human` | Only recruiter can confirm or remove the claim |
| Missing critical ToR requirement | high | `human` | Cannot conjure absent experience via rewriting |
| Experience gap below threshold (injected) | high | `human` | Arithmetic gap — no rewrite resolves it |
| Geographic requirement not met | high | `human` | Recruiter verifies alternative pathways |
| Language proficiency gap or inconsistency | high | `human` | Requires candidate confirmation |
| Filler / passive language | low | `pipeline` | Auto-fixed by LLM; field_editor can also handle |
| Missing action verb | low | `pipeline` | Auto-fixed; scalar rewrite |
| Exceeds word limit | low | `pipeline` | Auto-fixed; scalar tightening |
| Generic language / no sector keyword | low | `pipeline` | Auto-fixed; keyword injection |
| Whitespace / formatting | low | `pipeline` | Auto-fixed; normalised silently |

---

## What Did NOT Change

- The `run()` function signature is identical: `(run_dir: Path) -> tuple[CVData, bool]`
- `_precompute_context` is unchanged — it still runs before the LLM call and its output is injected into `<pre_computed>`
- `_enforce_passed_field` is unchanged
- `_filter_word_count_pedantry` is unchanged
- `_inject_experience_gap_finding` is unchanged except for the added `"solvability": "human"` key on the injected finding
- The step manifest updates (`update_step` calls) are identical
- The `generated_fields.json` write pattern is identical
- Pipeline flow (blocked vs passed, `reviewer_blocked` status) is identical
