# Renderer Issues — Developer Handoff

**Scope**: Known rendering defects in `templates/giz.py`,
`templates/giz_dynamic_template.py`, and `templates/wb.py`. All issues are
deterministic and reproducible. No LLM calls are involved in the renderer — all
fixes are pure Python.

**Cross-reference**: These issues are referenced in `PIPELINE_DIAGNOSTIC_CONTEXT.md`
Section 5 and `PIPELINE_DIAGNOSTIC_ROUND_8.md` (Issue R8-5). Full pipeline
diagnostic context is maintained separately — this file covers only renderer and
mapper defects with sufficient detail for an independent developer to implement
the fixes without access to the diagnostic history.

**Reference files**:
- `templates/giz.py` — GIZ `_build_context` and rendering entry point
- `templates/giz_dynamic_template.py` — GIZ XML preprocessor and table expander
- `templates/wb.py` — WB `_build_context` and rendering entry point
- `templates/wb_dynamic_template.py` — WB XML preprocessor and table expander
- `pipeline/precompute_utils.py` — shared date parsing utilities

---

## Issue A — `countries_of_experience` empty `date_to` sorts incorrectly

**Found**: Round 7.5, Run 4 (Merita Kostari).

**File**: `pipeline/agents/cv_tor_mapper.py` — post-processing sort step

**What happens**: Entries with an empty `date_to` (no recorded end date) sort
below entries with a specific end year, placing them at the bottom of the
countries table. The expected behaviour is:
- `date_to = "Present"` → top (ongoing assignment)
- `date_to = ""` (empty, no end date recorded) → treat as ongoing; sort above
  entries with a specific end date, since the absence of an end date implies the
  assignment may be continuing
- `date_to = "2019"` → sort below ongoing entries, descending by year

**Root cause**: The sort key uses `_parse_date(date_to)` which returns `None` for
empty strings. `None` values sort as `(0, 0)` (the fallback in the sort key
lambda), placing them below all dated entries.

**Fix A**: In the `countries_of_experience` sort key, treat `None` (unparseable
or empty `date_to`) as `_current_date()` — equivalent to ongoing — so entries
without a recorded end date float to the top alongside "Present" entries:

```python
from pipeline.precompute_utils import _parse_date, _current_date

def _country_sort_key(ce: dict) -> tuple:
    parsed = _parse_date(ce.get("date_to", ""))
    return parsed if parsed is not None else _current_date()

countries_sorted = sorted(
    countries_of_experience,
    key=_country_sort_key,
    reverse=True,
)
```

---

## Issue B — `countries_of_experience` trailing dash when `date_to` is empty

**Found**: Round 7.5 post-implementation testing, Run 1 (Keith Katyora).

**File**: `templates/giz_dynamic_template.py` — `country_subs`

**What happens**: When a `countries_of_experience` entry has `date_from` set but
`date_to` empty, the date cell renders with a trailing dash and blank:

```
2023 -
2018 -
```

The correct rendering is to show only `date_from` with no separator when
`date_to` is absent:

```
2023
2018
```

**Root cause**: `country_subs` hardcodes the date range as:

```python
f"{{{{ countries_of_experience[{i}].date_from }}}} - {{{{ countries_of_experience[{i}].date_to }}}}"
```

The ` - ` separator is unconditional. When `date_to` is empty, Jinja2 renders it
as an empty string, leaving a trailing dash.

`giz.py` `_build_context` already computes a `date_range` field per country entry
that handles this correctly:

```python
date_range = (
    f"{date_from} \u2013 {date_to}" if (date_from and date_to) else (date_from or date_to)
)
```

However, `country_subs` does not use this pre-computed value.

**Fix B** (preferred): Use the pre-computed `date_range` field in `country_subs`.
Change the cell_j==1 substitution from the two-variable construction to a single
`date_range` variable:

```python
elif cell_j == 1:
    p2 = _replace_text_in_para(
        p2,
        "{{ ce.date_range }}",
        f"{{{{ countries_of_experience[{i}].date_range }}}}",
    )
```

`date_range` is already present in each country entry dict in the context —
`giz.py` `_build_context` computes and includes it. No change to `_build_context`
needed.

---

## Summary

| Issue | Found | File | Type |
|-------|-------|------|------|
| A — Empty `date_to` sorts to bottom | Round 7.5 Run 4 | `pipeline/agents/cv_tor_mapper.py` | Sort key |
| B — Trailing dash on empty `date_to` | Round 7.5 Run 1 | `templates/giz_dynamic_template.py` | Substitution logic |

Issues A and B are independent. Both are isolated to `countries_of_experience`
handling. WB renderer has no open issues at this time.
