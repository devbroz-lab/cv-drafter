# Pipeline technical context

Single reference for **data flow**, **HTTP requests**, and **implementation mechanics**. Scope: `cv-drafter` FastAPI backend and background pipeline.

---

## 1. Architecture layers

| Layer | Role |
|-------|------|
| **HTTP** (`api/`) | JWT auth (Supabase), session CRUD, uploads, signed URLs; pipeline steps triggered via `BackgroundTasks`. |
| **Persistence** | Supabase Postgres (`sessions` row) + Supabase Storage (binary blobs). |
| **Orchestration** (`pipeline/orchestrator.py`) | Four phases; updates DB status + manifest steps; Phase 3 runs fields_generator → content_reviewer → compressor then halts at `checkpoint_3_pending`; Phase 4 calls `get_renderer(target_format)` and uploads final `output.docx`. Post-completion field edits are applied synchronously by `run_field_editor_task` before transitioning to `checkpoint_3_pending` again. |
| **Agents** (`pipeline/agents/`) | Six manifest steps (`cv_extractor`, `tor_summarizer`, `cv_tor_mapper`, `fields_generator`, `content_reviewer`, `compressor`) plus `field_editor` (post-completion, no manifest step) and deterministic text extraction (`pipeline/extractor`). |
| **Renderers** (`templates/giz.py`, `templates/wb.py`) | Static donor `.docx` → run-scoped dynamic template → **`docxtpl`** → **`runs/{session_id}/output.docx`**. |
| **Dispatch** (`templates/registry.py`) | **`get_renderer(target_format)`** only maps `giz` / `world_bank` → `giz.run` / `wb.run`. Renderer choice is keyed off the session row’s `target_format`. |

Compression does **not** go through this registry. How **`target_words`** and **`compression_ratio`** are set is documented in **§9** (only place that needs the full detail).

| `pipeline/config.py` | Pipeline-wide constants: `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS`, `EXPERIENCE_GAP_BLOCK_THRESHOLD_YEARS`, `WORD_COUNT_TOLERANCE_PCT`. Imported by `content_reviewer`. |
| `pipeline/validation.py` | Deterministic helpers used by `content_reviewer` pre/post-processing: `extract_role_tier`, `extract_required_years_for_tier`, `total_documented_years`, `cross_reference_geo_alternative`. No LLM calls. |
| `pipeline/precompute_utils.py` | Shared pre/post-compute helpers (P2/P15/P16/P17 fixes): `count_words`, `count_words_per_field`, `count_compressible_words_total`, `compute_project_duration`, `compute_project_year`, `restore_protected_fields`. Used by `fields_generator` (date pre-fill) and `compressor` (word-count pre-compute + protected-field restore). No LLM calls. |

---

## 2. Dual progress model

- **Coarse**: DB column `sessions.status` — `queued`, `processing`, `checkpoint_*_pending`, `reviewer_blocked`, `completed`, `failed` (see [`api/models/requests.py`](api/models/requests.py) `SessionStatus`). `field_editor_pending` remains a valid status value in the DB schema for backward compatibility but is no longer entered by new sessions.
- **Fine**: `runs/{session_id}/manifest.json` — ordered steps (`STEP_ORDER` in [`pipeline/manifest.py`](pipeline/manifest.py)) with per-step statuses defined in that module’s docstring: `waiting`, `running`, `done`, `failed`, **`blocked`** (content reviewer), **`pending`** (checkpoint waiting for approval), **`approved`** (checkpoint approved via HTTP).

Clients may poll **`GET /sessions/{id}/status`** (DB fields + signed `download_url` when `completed`) and **`GET /sessions/{id}/manifest`** (`steps`, `checkpoint_pending`, `reviewer_blocked`).

---

## 3. End-to-end data flow

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant Storage as SupabaseStorage
    participant DB as SupabaseDB
    participant Orch as Orchestrator
    participant Run as runs_session_dir

    Client->>API: POST /sessions
    API->>DB: insert session row
    Client->>API: POST .../upload/source (multipart)
    API->>Storage: put bytes
    API->>DB: update source_storage_key
    Client->>API: POST .../upload/tor
    Client->>API: POST .../start
    API->>Orch: BackgroundTasks run_phase1
    Orch->>Storage: download source (+ tor if tor_storage_key)
    Orch->>Run: extract text; agents 1+2 parallel; manifest + params
    Orch->>DB: checkpoint_1_pending
    Client->>API: POST .../approve/checkpoint_1
    API->>Orch: run_phase2 then ... approve/checkpoint_3 -> run_phase4
    Orch->>Run: phase2 mapper; phase3 generator/reviewer/compressor; phase4 renderer
    Orch->>Storage: upload output.docx
    Orch->>DB: completed + output_storage_key
```

**Artifact lineage (happy path)**

1. **Bytes**: CV (and optional ToR) → Storage keys on the session row.
2. **Text**: Phase 1 downloads bytes → **`pipeline.extractor.extract_text`** (`.docx` / `.pdf`) → plain text for agents.
3. **Structured JSON** under `runs/{session_id}/`:  
   `cv_data.json`, `tor_data.json` → `mapped_cv.json` → **`generated_fields.json`** (`generated`, optional `review` / `compression` / `generation_warnings`, updated through generator → reviewer → compressor).
4. **Word**: Phase 4 reads **`generated_fields.json`** → **`["generated"]`** → renderer writes **`runs/{session_id}/output.docx`** → upload → DB `output_storage_key`. For post-completion field-edit revisions, `field_editor` mutates `generated_fields.json["generated"]` in place before Phase 4 re-runs.

**Storage object path for final output**: [`build_object_path`](api/services/storage.py) `{session_id}/output/{safe_basename}` with basename `round_{NN}_{target_format}.docx` where `NN` is zero-padded from `sessions.round` and `target_format` comes from the session row ([`run_phase4`](pipeline/orchestrator.py)). Bucket name is configured separately (`SUPABASE_STORAGE_BUCKET`), not part of this key string.

---

## 4. Phases and agents (orchestrator)

| Phase | Entry | Agents / work | DB halt |
|-------|--------|----------------|---------|
| **1** | `run_phase1` | Downloads source; optional ToR extract; **`create_manifest`** with **`params = _build_params(row)`**; parallel **`cv_extractor`**, **`tor_summarizer`** (ToR summarizer runs with empty text if no file); deletes temp file under `input/` in `finally` | `checkpoint_1_pending` |
| **2** | `run_phase2` | **`cv_tor_mapper`** (`_run_if_needed` skips if manifest already `done`) | `checkpoint_2_pending` |
| **3** | `run_phase3` | **`fields_generator`** → **`content_reviewer`** (non-blocking; records review in `generated_fields.json`) → **`compressor`** | `checkpoint_3_pending` |
| **3 resume** | `run_phase3_resume` | Compressor path only (`_run_compressor_and_halt`); called by **`POST /resolve`** after reviewer block is cleared | `checkpoint_3_pending` |
| **Post-completion** | `run_field_editor_task` (synchronous, called inline by HTTP handler) | **`field_editor`** applies user-directed edits to `generated_fields.json["generated"]` with context enrichment (donor format, word limits, CV context snippet); resets `checkpoint_3` + `renderer` manifest steps | `checkpoint_3_pending` |
| **4** | `run_phase4` | Always calls **`set_processing`** first. If manifest **`renderer`** is already **`done`**, logs a warning and **`return`**s: **no upload**, **no `set_done`**, status stays **`processing`** (see **`reset_stale_processing_sessions`** on startup). Otherwise: **`update_step(renderer, running)`** → **`get_renderer(target_format)(session_id)`** → **`update_step(renderer, done)`** → **`upload_bytes`** → **`update_session_storage_keys(..., output_storage_key=...)`** → **`set_done`** (`status=completed`, `output_file_path` set to the same storage key string). | — |

**Manifest step order** ([`STEP_ORDER`](pipeline/manifest.py)):  
`cv_extractor` → `tor_summarizer` → `checkpoint_1` → `cv_tor_mapper` → `checkpoint_2` → `fields_generator` → `content_reviewer` → `compressor` → `checkpoint_3` → `renderer`.

**`field_editor` has no manifest step.** It is post-completion only, triggered by `POST /field-edit`, and tracked via the DB status transition (`processing` → `checkpoint_3_pending`) rather than the manifest.

**Agents and manifest**: Each agent sets its step to **`running`** / **`done`** / **`failed`**; **`content_reviewer`** may set **`blocked`**. Checkpoints **`pending`** (or **`approved`** after HTTP approve) are updated by the orchestrator or [`approve_checkpoint`](api/routers/sessions.py).

**Pipeline params**: [`_build_params`](pipeline/orchestrator.py) builds the dict persisted in **`manifest.params`** at Phase 1 (user-facing job fields, **`page_limit`**, etc.). Compressor keys **`target_words`** / **`compression_ratio`**: see **§9**.

**Idempotency**: [`_run_if_needed`](pipeline/orchestrator.py) skips a step when its manifest status is **`done`** (Phase 2–3 resume paths).

---

## 5. Renderer dispatch (Phase 4)

- **`templates/registry.py`** → `giz` → [`templates/giz.run`](templates/giz.py); `world_bank` → [`templates/wb.run`](templates/wb.py). Unsupported values raise **`ValueError`**.

Canonical static inputs: **`templates/GIZ-Template.docx`**, **`templates/WB-Template.docx`** (see [`pipeline/paths.py`](pipeline/paths.py)).

Full render flow (unpack → preprocess → zip → **`DocxTemplate`**) lives in **`RENDERER_CONTEXT.md`**.

---

## 6. HTTP surface (pipeline-driving requests)

**Auth**: `Authorization: Bearer <Supabase JWT>` for protected routes (see **`GET /health`** for the public probe).

**Typical sequence**

| Order | Method | Path | Purpose |
|-------|--------|------|---------|
| 1 | `POST` | `/sessions` | Create session; **`target_format`**, `source_filename`, optional job metadata. Compressor limits: **§9** (not client-tunable in normal flows). |
| 2 | `POST` | `/sessions/{id}/upload/source` | Multipart CV `.docx` / `.pdf`; guards on status. |
| 3 | `POST` | `/sessions/{id}/upload/tor` | Optional ToR. |
| 4 | `POST` | `/sessions/{id}/start` | `queued` only; requires `source_storage_key`; schedules **`run_phase1`**. |
| — | `POST` | `/sessions/{id}/tor/select-pool` | Prune **`tor_data.json.pools`** to the chosen pool only, set **`selected_pool_index` = 0** (request body index is into the pre-prune list). |
| — | `GET` | `/sessions/{id}/status` | Coarse status; signed **`download_url`** when `completed` and output key exists. |
| — | `PATCH` | `/sessions/{id}/status` | Updates session **`status`** (see router). |
| — | `GET` | `/sessions/{id}/manifest` | Steps + checkpoint/reviewer hints. |
| — | `GET` | `/sessions/{id}/output` | JSON from **`runs/.../generated_fields.json`**: **`generated`**, optional **`review`** / **`compression`** / **`generation_warnings`**. This is **not** the Word file; download uses **`output_storage_key`** + signed URL routes. |
| 5 | `POST` | `/sessions/{id}/approve/checkpoint_1` | Requires pruned ToR state: `pools` length 1 and `selected_pool_index` 0 (after pool selection), then sets checkpoint step **`approved`**, stamps `cv_data.json` / `tor_data.json`, schedules **`run_phase2`**. |
| 6 | `POST` | `/sessions/{id}/approve/checkpoint_2` | Stamps **`mapped_cv.json`**, schedules **`run_phase3`**. |
| — | `POST` | `/sessions/{id}/field-edit` | Valid only at **`completed`**; applies up to 5 targeted edits to `generated_fields["generated"]` via `field_editor` agent; increments `round`; transitions synchronously to **`checkpoint_3_pending`**. Does not re-run `fields_generator`, `content_reviewer`, or `compressor`. |
| — | `GET` | `/sessions/{id}/review` | Review payload from **`generated_fields.json`** when blocked. |
| — | `POST` | `/sessions/{id}/resolve` | Applies optional overrides / `force_pass`; may set reviewer step **`done`**; schedules **`run_phase3_resume`**. |
| 7 | `POST` | `/sessions/{id}/approve/checkpoint_3` | Stamps **`generated_fields.json`**, schedules **`run_phase4`**. |
| — | `GET` | `/sessions/{id}/files/output/download-url` | Dedicated signed URL for the output object. |

**Post-completion field-edit** (`status` must be **`completed`**): **`POST /sessions/{id}/field-edit`** calls [`increment_round`](api/services/database.py) (DB `sessions.round` **is** incremented), then `set_processing`, then runs `run_field_editor_task` **synchronously** inside the HTTP handler. `run_field_editor_task` calls `field_editor.run`, resets the `checkpoint_3` manifest step to `pending` and `renderer` to `waiting`, then calls `set_checkpoint_pending(session_id, 3)`. The HTTP response returns `status: "checkpoint_3_pending"` with `applied`/`skipped`/`round` lists. Approving `checkpoint_3` re-runs Phase 4; `build_object_path` uses the incremented `round` from the DB, producing `round_02_giz.docx`, `round_03_giz.docx`, etc.

**Deprecated revision** (`POST /sessions/{id}/comments`): still functional but emits `Deprecation: true` headers. It does **not** call `increment_round` — `sessions.round` is not advanced. The response `round` field is `current_round + 1` (a preview label only). Schedules `run_phase3_resume` (compressor path). Use `POST /field-edit` instead.

---

## 7. Local run directory layout

Root: [`pipeline/paths.RUNS_ROOT`](pipeline/paths.py) → **`cv-drafter/runs/{session_id}/`** (`_BACKEND_ROOT / "runs"`, resolved from **`pipeline/paths.py`**, not the process CWD).

**`session_id`**: Stored as the primary key on **`sessions`** (UUID from Supabase on create). [`validate_run_id`](pipeline/paths.py) restricts filesystem paths to alphanumerics plus **`_`** and **`-`** (max length 128) so arbitrary paths cannot escape **`RUNS_ROOT`**.

Typical files:

- `manifest.json` ( **`params`** , **`steps`** , provenance **`cv_path` / `tor_path`** )
- `input/` (Phase 1 temp; source blob file removed after Phase 1 `finally`)
- `cv_data.json`, `tor_data.json`, `mapped_cv.json`, `generated_fields.json`
- `preview.docx` (legacy local-only artifact; no longer produced by the normal pipeline; may exist on sessions created before the field-editor migration)
- `output.docx` (after Phase 4)
- Per-format dynamic template artifacts: e.g. `GIZ-Template.dynamic.docx` + `_giz_template_unpacked/`, or WB equivalents (names from `paths.py`)

`tor_data.json` envelope: `{"approved": bool, "approved_at": str|null, "pools": [...], "selected_pool_index": int|null}`. After Phase 1, `pools` may list multiple expert roles and `selected_pool_index` is null until the UI calls **select-pool**, which **drops unselected pools** and normalizes to **`pools`: one element, `selected_pool_index`: 0**. Downstream agents resolve ToR input from `pools[selected_pool_index]` (legacy `data` is fallback-only in helper code).

**Audit stamping**: Approving checkpoints calls [`pipeline/artifacts.stamp_approved`](pipeline/artifacts.py) on the corresponding JSON files (non-blocking on failure).

---

## 8. External dependencies

| System | Use |
|--------|-----|
| **Supabase Auth** | JWT verification; sessions scoped by `user_id`. |
| **Supabase Postgres** | Session row lifecycle and metadata. |
| **Supabase Storage** | CV, ToR, output blobs; signed URLs for download. |
| **Anthropic** | LLM agents (`Anthropic()` in agent modules). |

**Env** (see `.env.example`): `SUPABASE_*`, `ANTHROPIC_API_KEY`, optional bucket/CORS.

**Startup** ([`api/server.py`](api/server.py) lifespan): [`reset_stale_processing_sessions`](api/services/database.py) runs once. It sets **`failed`** (with a restart message) for rows stuck in **`processing`** or **`field_editor_pending`** (legacy) so crashes/redeploys do not leave sessions permanently frozen. It does **not** change **`queued`**, **`checkpoint_*_pending`**, **`reviewer_blocked`**, **`completed`**, or **`failed`**.

---

## 9. Compression parameters (`target_words`, `compression_ratio`)

Compressor limits are **not** read from environment variables. They are **not** written by [`create_session_row`](api/services/database.py) from [`SessionCreateRequest`](api/models/requests.py) optional fields (the request model includes them; the insert payload **omits** them).

**Where they live at runtime**

- [`_build_params`](pipeline/orchestrator.py) computes both values from **`get_session_row(session_id)`** at the start of Phase 1 plus [`FORMAT_PROFILES`](models.py) / literals.
- The full dict is stored under **`manifest.json`** → **`params`** when [`create_manifest`](pipeline/manifest.py) runs. Those entries do **not** update automatically if the DB row changes later.
- [`_run_compressor_and_halt`](pipeline/orchestrator.py) reads **`int(manifest["params"].get("target_words", 0) or 0)`** and **`float(manifest["params"].get("compression_ratio", 0.80) or 0.80)`** and passes them to [`compressor.run`](pipeline/agents/compressor.py). The agent sets **`effective_target = target_words if target_words > 0 else int(current_words * compression_ratio)`**; if **`current_words <= effective_target`**, it skips the LLM and writes a **`compression`** block with **`applied: false`**.

**Precedence inside `_build_params`** (highest first)

1. **`sessions` row** — non-null **`target_words`** / **`compression_ratio`** columns, if present in the row returned by Supabase.
2. **[`FORMAT_PROFILES[donor]`](models.py)** — **`default_target_words`**, **`default_compression_ratio`** for **`donor`** = normalized **`target_format`**.
3. **Literals** — **`target_words = 0`**, **`compression_ratio = 0.80`** if the donor has no profile.

**Shipped donor defaults**: **`giz`** and **`world_bank`** each define **`default_target_words = 0`** and **`default_compression_ratio = 0.80`**. With no row overrides, **`manifest.params`** contains **`0`** and **`0.80`** for every normal session created through the HTTP API today.

---

## 10. Format profiles (generation, not rendering)

[`models.FORMAT_PROFILES`](models.py): per-**donor** configuration. **Fields generator** uses **`generative_field_keys`** and **`manifest.params.donor`** (e.g. GIZ **`key_qualifications`** vs World Bank **`detailed_tasks`**). **Compression defaults** on the same object are described in **§9**. **Rendering** must still match **`target_format`** templates on disk.

---

## 11. Process entry

```bash
uvicorn api.server:app --reload --host 127.0.0.1 --port 8000
```

Working directory: project root **`cv-drafter`** so `api`, `pipeline`, and `templates` import cleanly.
