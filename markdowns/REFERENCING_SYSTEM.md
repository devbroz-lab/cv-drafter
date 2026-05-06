# Referencing System — UI ↔ Backend Walkthrough

This document explains exactly how the DocxViewer's structural locators are generated,
why they are guaranteed to stay in sync with the backend template that produced the
document, and how they wire into the future edit agent.

---

## 1. What a "reference" is

A reference is a structural address for one piece of content inside `output.docx`.
It has two forms depending on whether the content lives in a paragraph or a table cell:

```json
// Paragraph reference
{
  "locator": {
    "location": "paragraph",
    "paragraph_index": 12,
    "text_content": "Led grid rehabilitation across 3 pilot provinces"
  },
  "comment": "Change to mention Kenya specifically"
}

// Table cell reference
{
  "locator": {
    "location": "table",
    "table_index": 5,
    "row_index": 2,
    "cell_index": 3,
    "text_content": "Pristina, Kosovo"
  },
  "comment": "Update to Nairobi, Kenya"
}
```

`paragraph_index` and `table_index` are **zero-based counts of direct children of
`<w:body>` in document order** — the same order that Word's XML always uses.
`row_index` and `cell_index` are zero-based within their parent table.

---

## 2. How `output.docx` is built (the backend side)

Understanding the locator system requires understanding the two-step rendering process.

### Step A — Dynamic template preprocessing

The static donor template (`templates/GIZ-Template.docx` or `WB-Template.docx`) contains
Jinja2 loop markers like `{%tr for proj in relevant_projects %}` in its
`word/document.xml`. Word's XML format cannot express variable-length table rows
natively, so the preprocessor handles this before any Jinja rendering.

`templates/giz_dynamic_template.py` → `preprocess_document_xml(xml, counts)`:

1. Counts how many items are in each section (education, languages, projects, etc.)
   from the final `CVData` snapshot in `generated_fields.json["generated"]`.
2. For each data table, takes the single template row and replicates it N times,
   replacing generic loop variables with indexed direct-access expressions:
   ```
   {{ proj.location }}  →  {{ relevant_projects[0].location }}
                           {{ relevant_projects[1].location }}
                           ...{{ relevant_projects[N-1].location }}
   ```
3. For bullet lists outside tables (key qualifications, publications), replaces
   `{% for kq in key_qualifications %}...{% endfor %}` with N copies of the
   body paragraph, each referencing `key_qualifications[0]`, `[1]`, etc.
4. Writes the rewritten XML back and re-zips to
   `runs/{session_id}/GIZ-Template.dynamic.docx`.

The result is a `.docx` file whose `word/document.xml` has **exactly N table rows
for each section** — no loop placeholders remain, only indexed Jinja variables.

### Step B — Jinja rendering

```python
DocxTemplate(dynamic_template_path).render(context)
```

`context` is built by `templates/giz.py` → `_build_context(cv_data)`. It maps
the `CVData` dict into template-ready Python objects (CEFR-mapped languages,
formatted date ranges, resolved key qualifications, etc.).

After rendering, every `{{ relevant_projects[2].location }}` is replaced with
the actual string from CVData. The result is `runs/{session_id}/output.docx`.

### Step C — Upload

The orchestrator (`pipeline/orchestrator.py` → `run_phase4`) reads `output.docx`
bytes and uploads to Supabase Storage at:
```
{session_id}/output/round_{NN}_{target_format}.docx
```
The storage key is saved to the `sessions` DB row and the status transitions to
`completed`.

---

## 3. How the DocxViewer generates locators (the UI side)

**File:** `src/components/DocxViewer.tsx`

When the user clicks "View Document" on the completed session page:

```
SessionWorkspacePage
  → runOpenViewer()
  → GET /sessions/{id}/files/output/download-url   (backend API)
  → Supabase Storage signed URL (60s–1h expiry)
  → setViewerDocxUrl(signed_url)
  → <DocxViewer docxUrl={signed_url} /> mounts
```

Inside `DocxViewer` on mount (`useEffect`):

```
fetch(docxUrl)
  → ArrayBuffer
  → JSZip.loadAsync(arrayBuffer)
  → zip.file("word/document.xml").async("string")
  → DOMParser.parseFromString(xmlString, "text/xml")
  → parseDocumentXml(xmlDoc)
```

`parseDocumentXml` walks `xmlDoc.body.children` in document order:

```typescript
for (const elem of Array.from(body.children)) {
  if (elem.localName === "p") {
    // Top-level paragraph
    blocks.push({ kind: "paragraph", paragraphIndex: parCount, text });
    parCount++;
  } else if (elem.localName === "tbl") {
    // Table — walk rows and cells
    blocks.push({ kind: "table", tableIndex: tableCount, rows });
    tableCount++;
  }
}
```

Each block is rendered as a clickable HTML element. On click:

```typescript
// Paragraph click
addReference({
  location: "paragraph",
  paragraph_index: block.paragraphIndex,
  text_content: block.text,
});

// Cell click
addReference({
  location: "table",
  table_index: block.tableIndex,
  row_index: row.rowIndex,
  cell_index: cell.cellIndex,
  text_content: cell.text,
});
```

References accumulate in component state. The user annotates each with a
free-text comment. "Copy all as JSON" emits:

```json
[
  { "locator": { ... }, "comment": "..." },
  ...
]
```

---

## 4. Why the locators are guaranteed to be in sync

The viewer reads **the same `output.docx` bytes** that the backend produced and
uploaded to Supabase Storage. There is no intermediate representation.

The `parseDocumentXml` walk is identical to the logic in `docx-viewer.html` —
it counts direct `<w:body>` children in document order. The backend's dynamic
template preprocessor also operates on direct `<w:body>` children in document
order when it calls `_find_tables(xml)` and `expand_table(xml, tbl_idx, ...)`.
Both systems count the same elements.

Concretely: if the preprocessor says "table index 5 is the Relevant Projects
table" (because `expand_table(xml, 5, ...)` is the fifth `expand_table` call),
the viewer will also produce `table_index: 5` for every cell in that table —
because it is the fifth `<w:tbl>` element encountered when walking `<w:body>`.

**The indices are structural positions in the final XML — they never require
translation.**

---

## 5. GIZ document structure — locator → semantic field mapping

This table maps viewer locators to CVData dot-paths. It is derived directly from
`templates/giz_dynamic_template.py` → `preprocess_document_xml`.

### Tables

| table_index | Section | row_index | cell_index | CVData dot-path |
|---|---|---|---|---|
| 0 | Personal info header | varies | varies | `personal_info.*` |
| 1 | Education | N | 0 | `education[N].institution` + date range |
| 1 | Education | N | 1 | `education[N].degree` |
| 2 | Languages | N | 0 | `languages[N].language` |
| 2 | Languages | N | 1 | `languages[N].reading_cefr` |
| 2 | Languages | N | 2 | `languages[N].speaking_cefr` |
| 2 | Languages | N | 3 | `languages[N].writing_cefr` |
| 3 | Skills / Membership | varies | varies | `other_skills_display`, `membership_professional_bodies` |
| 4 | Countries of Experience | N | 0 | `countries_of_experience[N].country` |
| 4 | Countries of Experience | N | 1 | `countries_of_experience[N].date_from` + `date_to` |
| 5 | Relevant Projects | N | 0 | display index only (loop.index) |
| 5 | Relevant Projects | N | 1 | `relevant_projects[N].date_from` + `date_to` |
| 5 | Relevant Projects | N | 2 | `relevant_projects[N].location` |
| 5 | Relevant Projects | N | 3 | `relevant_projects[N].company` |
| 5 | Relevant Projects | N | 4 | `relevant_projects[N].positions_held` |
| 5 | Relevant Projects | N | 5 | `relevant_projects[N].project_name` + `main_project_features` |

> `N` in `row_index` directly maps to the list index in CVData. Row 0 = first
> item in the list, row 1 = second item, etc. The header row (row 0 of the
> template before expansion) becomes row 0 in the output if it is a static
> header; data rows start at row 1 in templates that have a header row.
> Always verify against the actual rendered docx using the viewer itself.

### Paragraphs (non-table content)

Paragraphs are counted across the **entire document body**, interleaved with
tables. They include all headings, section labels, and bullet content outside
of tables. The key qualifications and publications are expanded as inline
paragraph bullets.

To identify which `paragraph_index` corresponds to which CVData field, use the
viewer itself: click a paragraph, read its `text_content` and `paragraph_index`,
then cross-reference with the CVData dot-path. There is no static mapping because
paragraph indices shift with every run (they depend on how many lines of personal
info, how many education entries exist, etc.).

The dot-path for a key qualification bullet at paragraph index P:
```
key_qualifications[N]   (where N = bullet's position within the KQ block)
```

---

## 6. Dot-path resolution — the backend's existing traversal system

The backend already has a complete dot-path read/write system used by the
review and resolve pipeline.

**File:** `api/services/dot_path.py`

```python
get_by_dot_path(root, "relevant_projects.2.location")
# → root["relevant_projects"][2]["location"]

set_by_dot_path(root, "relevant_projects.2.location", "Nairobi, Kenya")
# → root["relevant_projects"][2]["location"] = "Nairobi, Kenya"
```

Rules:
- Numeric path segments address list indices
- Non-numeric segments address dict keys
- Paths are relative to the `"generated"` key inside `generated_fields.json`

This is the **same path format** used in:
- `POST /sessions/{id}/resolve` — `payload.overrides` dict maps dot-paths to new values
- `GET /sessions/{id}/review` — each `HighSeverityIssue.field` is a dot-path
- `GET /sessions/{id}/output` — `CVData` shape that the paths navigate

---

## 7. End-to-end data flow diagram

```
╔══════════════════════════════════════════════════════════════════════════╗
║  BACKEND PIPELINE                                                        ║
║                                                                          ║
║  generated_fields.json["generated"]  →  CVData (post Agent 6)           ║
║         ↓                                                                ║
║  giz.py _build_context(cv_data)      →  context dict                    ║
║         ↓                                                                ║
║  giz_dynamic_template.py             →  GIZ-Template.dynamic.docx       ║
║    expand_table(xml, 1, n_edu, ...)      (word/document.xml rewritten)  ║
║    expand_table(xml, 2, n_lang, ...)                                     ║
║    expand_table(xml, 4, n_countries,..)                                  ║
║    expand_table(xml, 5, n_projects, ..)                                  ║
║    expand_bullet_loop(key_qualifications)                                ║
║         ↓                                                                ║
║  DocxTemplate.render(context)        →  output.docx                     ║
║         ↓                                                                ║
║  Supabase Storage upload             →  {session_id}/output/round_NN.docx║
╚══════════════════════════════════════════════════════════════════════════╝
                              ↓
             GET /sessions/{id}/files/output/download-url
                              ↓
╔══════════════════════════════════════════════════════════════════════════╗
║  FRONTEND — DocxViewer.tsx                                               ║
║                                                                          ║
║  fetch(signed_url) → ArrayBuffer                                         ║
║  JSZip.loadAsync() → word/document.xml string                            ║
║  DOMParser         → XML DOM                                             ║
║  parseDocumentXml  → walk <w:body> direct children in order:            ║
║                        <w:p>   → { kind:"paragraph", paragraphIndex }   ║
║                        <w:tbl> → { kind:"table", tableIndex, rows }     ║
║         ↓                                                                ║
║  Render as clickable HTML                                                ║
║         ↓ (user clicks)                                                  ║
║  Locator: { location, paragraph_index | table_index+row+cell,           ║
║             text_content }                                               ║
║         ↓ (user adds comment)                                            ║
║  Reference: { locator, comment }                                         ║
║         ↓ (Copy all as JSON)                                             ║
║  [{locator, comment}, ...]                                               ║
╚══════════════════════════════════════════════════════════════════════════╝
                              ↓
╔══════════════════════════════════════════════════════════════════════════╗
║  FUTURE — Edit Agent (not yet built)                                     ║
║                                                                          ║
║  Input:  references JSON  +  natural language instruction               ║
║                                                                          ║
║  Path A — CVData field update + re-render                               ║
║    1. Map locator → CVData dot-path                                      ║
║       (using GIZ table structure table above)                           ║
║    2. Update CVData via set_by_dot_path(generated, dot_path, new_value) ║
║    3. Write back to generated_fields.json["generated"]                  ║
║    4. Re-run phase 4 (renderer) to produce new output.docx              ║
║    5. New round uploaded to Supabase Storage                             ║
║                                                                          ║
║  Path B — Direct XML edit (no re-render)                                ║
║    1. Fetch output.docx bytes                                            ║
║    2. Unzip → word/document.xml                                          ║
║    3. Walk to <w:body> child[table_index] or child[paragraph_index]     ║
║    4. Mutate the <w:t> text nodes at row+cell coords                    ║
║    5. Re-zip and re-upload                                               ║
║    (note: this diverges CVData from output.docx — Path A is preferred)  ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## 8. Existing endpoints the edit agent will use

| Endpoint | What it does | Agent use |
|---|---|---|
| `GET /sessions/{id}/output` | Returns full CVData + review + compression from `generated_fields.json` | Read current field values before patching |
| `GET /sessions/{id}/files/output/download-url` | Returns short-lived signed URL for `output.docx` | Download current rendered doc to inspect or for Path B edits |
| `POST /sessions/{id}/resolve` | Applies dot-path overrides to `generated_fields.json["generated"]` and re-runs compressor | **Path A entry point** — send `overrides: { "relevant_projects.2.location": "Nairobi, Kenya" }` |
| `POST /sessions/{id}/approve/checkpoint_3` | Triggers Phase 4 renderer | Re-render after resolve completes |
| `POST /sessions/{id}/comments` | Submits recruiter feedback, re-runs compressor → checkpoint_3 | High-level natural language revision loop |

`POST /resolve` is the most direct write path for the edit agent:
1. Agent receives locator → maps to dot-path using the table above
2. Agent sends `POST /resolve` with `overrides: { <dot-path>: <new_value> }`
3. Pipeline resumes from compressor → checkpoint_3_pending
4. User or agent approves checkpoint_3 → Phase 4 re-renders the docx

---

## 9. Signed URL expiry — timing note

The signed URL passed to `DocxViewer` is generated at the moment the user clicks
"View Document" and expires in **3600 seconds (1 hour)** by default (configured in
`GET /sessions/{id}/files/output/download-url`).

If the viewer is left open longer than that, the initial `fetch(docxUrl)` has
already completed and the parsed content is held in component state — the URL
expiry does not affect the already-loaded document. The URL is only needed for
the single initial fetch on mount.

---

## 10. World Bank format — locator differences

The WB format uses `templates/wb_dynamic_template.py` which has a **different
table layout**:

- Employment records replace countries of experience
- Detailed tasks are inserted per project
- Table indices will differ from the GIZ mapping above

A separate `REFERENCING_SYSTEM_WB.md` should be created once the WB template
structure is finalised. The DocxViewer itself is format-agnostic — it reads
whatever `output.docx` it is given and the locators are always structurally
correct. Only the semantic mapping table (section 5 above) changes between formats.
