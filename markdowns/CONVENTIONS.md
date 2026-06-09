---
title: Documentation Conventions
type: meta
status: current
owner: backend
last_verified: 2026-06-08
code_refs: []
related: [INDEX.md]
---

# Documentation Conventions

How the `markdowns/` docs are organised. Read this before adding or editing a doc.

## Principles

The directory a doc lives in **encodes its type**, and that determines whether it is kept
current or frozen:

| Type | Folder | Answers | Edited after merge? |
|------|--------|---------|---------------------|
| `meta` | `markdowns/` root | "How do the docs work?" | Yes |
| `reference` | `reference/` | "What is true **now**?" | Yes — kept current |
| `design` (ADR) | `design/` | "**Why / when** did we decide this?" | **No** — immutable |
| `frontend` | `frontend/` | "What is the contract for the UI team?" | Yes |

## Directory layout

```
markdowns/
  INDEX.md            # the map — every doc, one line
  CONVENTIONS.md      # this file
  reference/          # current-state truth, one canonical doc per topic
    pipeline-overview.md  data-model.md  extraction.md  orchestration.md
    artifacts.md  renderer.md  api.md
    agents/  a1-cv-extractor.md … a7-field-editor.md
  design/             # ADRs — numbered, dated, immutable
    0001-….md  0002-….md  …
  frontend/           # consumer-facing contracts
    progress-and-warnings.md
```

## The four golden rules

1. **`reference/` is current state only.** No inline version stamps — never write "as of Round 5",
   "R7-J", "previously…". When behaviour changes, **edit the reference to the new truth** and record
   the why/when as an ADR in `design/`.
2. **History lives in `design/` ADRs.** ADRs are append-only and immutable once merged; supersede an
   ADR with a newer ADR, don't edit the old one.
3. **Every reference doc cites its code** via front-matter `code_refs`, so drift between doc and
   source is detectable.
4. **Filenames are clean and stable.** kebab-case, no `_CONTEXT` / `_FIXES` / `_ROUND_N` suffixes,
   no version numbers in filenames. The folder already says the type.

## Front-matter (required on every file)

```yaml
---
title: A4 — Fields Generator
type: reference            # meta | reference | design | frontend
status: current            # current | superseded  (ADRs: accepted | superseded)
owner: backend             # backend | frontend | infra
last_verified: 2026-06-08  # date the doc was last checked against the code
code_refs:                 # source files this doc describes (paths from repo root)
  - pipeline/agents/fields_generator.py
related:                   # other docs / ADRs
  - reference/artifacts.md
  - design/0001-lean-agent-output-contracts.md
---
```

## Section template

**Reference doc:** Purpose → Role in the pipeline → Inputs → Outputs (artifacts & contracts) →
How it works → Contracts & invariants → Gotchas & failure modes → Code references → Related.

Cite source, don't re-paste it: link to `pipeline/agents/fields_generator.py`, describe the
contract and the invariants, and let the code be the detail.

**ADR (`design/NNNN-title.md`):** Context / problem → Decision → Consequences (good & bad) →
Alternatives considered → Code refs & branch/commit.

## Adding or deprecating a doc

- **New doc:** create it in the right type folder, fill the front-matter, add a row to `INDEX.md`.
- **Behaviour changed:** edit the affected `reference/` doc to the new truth, bump `last_verified`,
  and add an ADR describing the change.
- **Deprecate:** set `status: superseded` in the front-matter and in `INDEX.md`; point `related` at
  the replacement. Don't delete history-bearing ADRs.

## Conventions for agents A1–A7

The seven pipeline agents map one-to-one to `reference/agents/aN-*.md` and to
`pipeline/agents/*.py`. Reading one, you can always find the other.
