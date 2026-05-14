# Compression Calibration Context — TARGET_WORDS_PER_PAGE

**Status**: ⏳ Pending — insufficient data to calibrate. To be conducted when
enough clean rendered outputs are available.

**Related fix**: Fix S (`PIPELINE_DIAGNOSTIC_CONTEXT.md` Issue S)
**Target file**: `pipeline/config.py`

---

## Why this calibration is needed

The compressor currently uses a fixed `target_words` that is not scaled to
`page_limit`. In Round 4 Run 3 (GIZ, `page_limit=2`), the compressor applied
a 1-page target of 900 words, cutting 49% of content unnecessarily. Fix S
introduces `TARGET_WORDS_PER_PAGE` as a per-donor constant so that
`target_words = page_limit * TARGET_WORDS_PER_PAGE` is computed dynamically.

The constant cannot be set theoretically — it must be measured against real
rendered output, because page geometry is determined by the Word template's
fonts, margins, table structure, and fixed section headers, not by word count
alone.

---

## Calibration process (when data is available)

### What to collect

For each donor template (GIZ and WB), collect 2–3 rendered output `.docx`
files where:
- The page count matched the intended `page_limit` (or was acceptably close).
- The content density looked correct to a human reviewer.
- Ideally: at least one 1-page and one 2-page example per template.

Also note the `page_limit` param used for each run (from `manifest.json`).

### How to measure

1. Count the words in the **rendered output `.docx`** — not the source CV,
   not the pipeline artifacts. The rendered word count is what the template
   actually fits at that page count.
2. Divide by `page_limit`: `words_in_output / page_limit = words_per_page`.
3. Average across 2–3 samples per template to get a stable constant.
4. Repeat for each donor template independently — GIZ and WB have different
   layouts and will produce different constants.

### Validation step

Take a run that was over-compressed (e.g. Round 4 Run 3: 1,058 words,
`page_limit=2`, target was 900) and verify that
`page_limit * TARGET_WORDS_PER_PAGE` would have produced a sensible target
for that run.

---

## Expected output

Two constants to be added to `pipeline/config.py`:

```python
GIZ_WORDS_PER_PAGE = ???   # to be calibrated
WB_WORDS_PER_PAGE  = ???   # to be calibrated
```

And consumed in the orchestrator or compressor as:

```python
words_per_page = GIZ_WORDS_PER_PAGE if donor == "giz" else WB_WORDS_PER_PAGE
target_words = page_limit * words_per_page
```

---

## Notes

- WB templates tend to have more whitespace and table structure than GIZ —
  expect `WB_WORDS_PER_PAGE` to be lower than `GIZ_WORDS_PER_PAGE`.
- If the rendered document still exceeds `page_limit` after compression
  (Issue T — layout-driven overflow), that is a template issue and not
  addressable by adjusting this constant further.
- Once Fix 4 (Python relevance scoring) is in place and project selection
  is more consistent, re-validate these constants — a more complete project
  set may shift the typical word count range.
- Minimum 5 clean rendered outputs total (across both templates and page
  counts) before the constants should be considered stable.
