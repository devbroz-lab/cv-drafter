---
title: 0004 — Empty-field review flags, countries derivation, render placeholders, other_skills→str
type: design
status: accepted
owner: backend
last_verified: 2026-06-11
code_refs:
  - pipeline/agents/content_reviewer.py
  - pipeline/agents/cv_extractor.py
  - pipeline/utils/countries.py
  - templates/base.py
  - templates/giz.py
  - templates/wb.py
  - models.py
related:
  - reference/agents/a1-cv-extractor.md
  - reference/agents/a5-content-reviewer.md
  - reference/renderer.md
  - reference/data-model.md
---

# 0004 — Empty-field review flags, countries derivation, render placeholders, other_skills→str

## Context

A real GIZ run (candidate "Alias Wardak", a modern resume-style PDF) shipped a document with empty
`date_of_birth`, `nationality`, `place_of_residence`, and `countries_of_experience`, and nobody was
told. Two root problems:

1. **A5 doesn't flag important empty fields.** Its prompt is explicitly told *not* to flag missing
   optional fields, so a CV missing required identity data passed review silently.
2. **A1 leaves `countries_of_experience` empty** whenever the CV has no dedicated countries
   section — even though the geography is plainly present in each project's location line
   (`"08/2024 - Present, Essen / Germany"`, `"Sri Lanka, India, Bhutan, Nepal, Bangladesh"`). The A1
   prompt had no instruction to derive it.

Two related product requirements were added: empty required fields should still render a visible
placeholder in the output document, and `other_skills` should be free text (like
`membership_professional_bodies`) rather than a list.

## Decision

**1. Deterministic empty-required-field flags (A5).** A new post-processor
`_inject_empty_required_field_findings` (`pipeline/agents/content_reviewer.py`) injects a
high-severity `solvability: "human"` finding (`_injected_by_postprocessing: True`) for each empty
donor-required field, deduped against the LLM's own findings. It runs on the **post-fix generated
data**, so a `countries_of_experience` populated by decision (2) is never false-flagged. The required
set is the module-level `REQUIRED_FIELDS_BY_DONOR` (review policy, kept with the reviewer — not in
`models.FORMAT_PROFILES`). `_enforce_passed_field` (unchanged, still last) flips `passed=false`, so
these block the review step exactly like any high-severity finding. No frontend change — the existing
`solvability: "human"` chip renders them.

**2. countries_of_experience derivation (A1).** A prompt rule (derive one country per location, with
that entry's date range; cities/regions excluded) **plus** a deterministic Python safety net
`_derive_countries_from_projects` backed by `pipeline/utils/countries.find_countries` (word-boundary,
case-insensitive matching against an ISO-3166 list + curated alias/misspelling table; longest-match
wins). A1 emits **raw single-country rows**; A3's existing `collapse_by_date_range` + date sort own
the merge. A warning is appended whenever the list is derived rather than extracted.

**3. Render-time placeholders.** `templates/base.NOT_FOUND_PLACEHOLDER` (`"[Not found in source CV]"`)
is substituted inside each renderer's `_build_context` for the same donor-required fields; empty
required tables get one placeholder row. Placeholders live **only** in the render context — artifacts
keep `""`/`[]`.

**4. `other_skills: list[str] → str`.** Now free text, joined with `"; "`, with a
`@field_validator(mode="before")` coercing legacy list/None values so old artifacts re-validate
cleanly. Renderers, `precompute_utils.count_words_per_field`, and the compressor prompt updated to
treat it as one string.

## Consequences

**Good.** Required gaps are now impossible to miss — flagged for the recruiter, blocking the review,
and visible in the document. Resume-style CVs get a populated geography section. The empty-field
policy lives in one donor-aware table shared (in spirit) by the reviewer and the renderers.

**Bad / watch.** Existing sessions re-reviewed after this change will show more high-severity findings
(more `passed=false`) — expected, but the volume rises. A7 doc-viewer edits that click a placeholder
paragraph won't fuzzy-match a real field (underlying value is `""`) and are skipped with a reason.
Legacy `other_skills[N]` edit paths from the current UI no longer resolve server-side (skipped
best-effort) until the frontend follow-up (`cv-drafter-ui/src/lib/utils/locatorToDotPath.ts`) treats
`other_skills` as a single editable string.

## Alternatives considered

- **Required-field config in `FORMAT_PROFILES` (models.py).** Rejected — it is review/render policy,
  not schema; coupling the data model to A5 behaviour is the wrong layer.
- **Collapsing countries at A1.** Rejected — A3 already collapses by exact `(date_from, date_to)`;
  pre-joining at A1 produces multi-country strings that break that exact-string re-collapse.
- **Fuzzy country matching.** Rejected — non-deterministic; a curated alias/misspelling table covers
  the real cases without false positives.
- **Storing placeholders in the artifact JSON.** Rejected — would force every downstream consumer
  (A5 emptiness check, A7 edits, compressor) to special-case the placeholder string.
- **Prompt-only flagging / prompt-only countries.** Rejected — no safety net if the model still omits
  the field; the whole point is a deterministic guarantee.
