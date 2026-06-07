"""
Pipeline orchestrator — phase-based background tasks for the 6-agent CV pipeline.

Execution model
---------------
The pipeline is split into 4 phases, each registered as a FastAPI BackgroundTask.
Between phases, the pipeline halts and updates the DB status to a checkpoint_N_pending
value.  The frontend polls GET /sessions/{id}/status and shows an approval UI.
When the user approves, the approve endpoint schedules the next phase.

Phase 1  (run_phase1)  — Agents 1 & 2 in parallel → checkpoint_1_pending
Phase 2  (run_phase2)  — Agent 3 → checkpoint_2_pending
Phase 3  (run_phase3)  — Agents 4, 5, 6 → checkpoint_3_pending | reviewer_blocked
Phase 4  (run_phase4)  — Renderer (GIZ or World Bank) → upload output.docx → completed

Each phase:
  • Calls set_processing() at the top.
  • Calls set_checkpoint_pending() or set_done() at the bottom on success.
  • Calls set_failed() in the except block.
  • Phase 1 only: deletes the temp input file in the finally block.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from api.services.database import (
    get_session_row,
    set_checkpoint_pending,
    set_done,
    set_failed,
    set_processing,
    update_session_storage_keys,
)
from api.services.storage import build_object_path, download_bytes, upload_bytes

from pipeline.agents import (
    compressor,
    content_reviewer,
    cv_extractor,
    cv_tor_mapper,
    field_editor,
    fields_generator,
    tor_summarizer,
)
from pipeline.extractor import extract_text
from pipeline.manifest import append_warning, create_manifest, get_step_status, update_step
from pipeline.validators import (
    PipelineValidationError,
    alignment_warnings_for_manifest,
    check_compressor_warnings,
    check_content_reviewer_warnings,
    check_fields_generator_warnings,
    check_tor_summarizer_warnings,
    extraction_warnings_for_manifest,
    generation_warnings_for_manifest,
    review_summary_for_manifest,
    validate_fields_generator_output,
)
from pipeline.paths import RUNS_ROOT, get_run_dir

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_params(row: dict) -> dict:
    """Assemble the params dict the pipeline agents expect from a DB session row."""
    return {
        "proposed_position": row.get("proposed_position") or "",
        "category": row.get("category") or "",
        "employer": row.get("employer") or "",
        "years_with_firm": row.get("years_with_firm") or "",
        "donor": (row.get("target_format") or "giz").lower(),
        "page_limit": row.get("page_limit"),
        "job_description": row.get("job_description") or "",
        "recruiter_comments": row.get("recruiter_comments") or "",
    }


def _run_if_needed(run_dir: Path, step_name: str, fn, *args, **kwargs) -> None:
    """Skip a step if its manifest status is already 'done'."""
    if get_step_status(run_dir, step_name) == "done":
        return
    fn(*args, **kwargs)


def _emit_warnings(run_dir: Path, session_id: str, warns: list[dict]) -> None:
    """Log + append a list of warning dicts to manifest.json (idempotent).

    Used to stream agent warnings onto the polled /manifest channel as each
    phase completes. ``append_warning`` de-dupes identical (stage, kind, message).
    """
    for w in warns:
        log.info("Session %s soft-flag [%s]: %s", session_id, w["kind"], w["message"])
        append_warning(run_dir, **w)


# ---------------------------------------------------------------------------
# Phase 1 — Agents 1 & 2 (parallel extraction)
# ---------------------------------------------------------------------------


async def run_phase1(
    *,
    session_id: str,
    source_storage_key: str,
    source_filename: str,
    target_format: str,
    tor_storage_key: str | None = None,
) -> None:
    """
    Download source CV, extract text, run Agents 1 & 2 in parallel,
    then halt at checkpoint_1_pending.

    The temp source file is written to runs/{session_id}/input/ and deleted
    in the finally block regardless of success or failure.
    """
    input_path: Path | None = None
    set_processing(session_id)

    try:
        # ── Download source → temp file ───────────────────────────────────
        source_bytes = download_bytes(source_storage_key)
        input_dir = RUNS_ROOT / session_id / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(source_filename).name or "source.bin"
        input_path = input_dir / safe_name
        input_path.write_bytes(source_bytes)

        # ── Read full session row for params ──────────────────────────────
        row = get_session_row(session_id) or {}

        # ── Extract ToR text (if uploaded) ────────────────────────────────
        tor_text = ""
        if tor_storage_key:
            try:
                tor_bytes = download_bytes(tor_storage_key)
                # Use the stored tor_filename for extension detection; fall back to
                # the storage key itself (which preserves the original filename in
                # its last path segment via build_object_path).
                tor_filename = row.get("tor_filename") or tor_storage_key
                tor_text = extract_text(tor_filename, tor_bytes)
            except Exception as tor_exc:
                log.warning("Could not extract ToR text for session %s: %s", session_id, tor_exc)
        params = _build_params(row)

        # ── Create run directory + manifest ───────────────────────────────
        run_dir = get_run_dir(session_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        create_manifest(
            run_dir,
            run_id=session_id,
            cv_path=str(input_path),
            tor_path=tor_storage_key or "",
            params=params,
        )

        # ── Extract CV text ───────────────────────────────────────────────
        cv_text = extract_text(source_filename, source_bytes)

        # ── Agents 1 & 2 in parallel ──────────────────────────────────────
        def _agent1() -> None:
            cv_extractor.run(run_dir, cv_text, params)

        def _agent2() -> None:
            tor_summarizer.run(run_dir, tor_text)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(_agent1)
            f2 = executor.submit(_agent2)
            f1.result()  # re-raises any exception from agent 1
            f2.result()  # re-raises any exception from agent 2

        # R6-D: soft-flag check after A2 for empty scoring_keywords
        for w in check_tor_summarizer_warnings(run_dir):
            log.info("Session %s soft-flag [%s]: %s", session_id, w["kind"], w["message"])
            append_warning(run_dir, **w)

        # Stream A1 extraction warnings onto the polled /manifest channel.
        _emit_warnings(run_dir, session_id, extraction_warnings_for_manifest(run_dir))

        # ── Halt at checkpoint 1 ──────────────────────────────────────────
        update_step(run_dir, "checkpoint_1", "pending")
        set_checkpoint_pending(session_id, 1)
        log.info("Session %s reached checkpoint_1_pending", session_id)

    except Exception as exc:
        log.exception("Session %s phase 1 failed: %s", session_id, exc)
        set_failed(session_id, str(exc))

    finally:
        if input_path is not None:
            input_path.unlink(missing_ok=True)
            log.debug("Deleted temp input file %s", input_path)


# ---------------------------------------------------------------------------
# Phase 2 — Agent 3 (CV-ToR Mapper)
# ---------------------------------------------------------------------------


async def run_phase2(*, session_id: str) -> None:
    """
    Run Agent 3 (CV-ToR Mapper) and halt at checkpoint_2_pending.
    """
    set_processing(session_id)
    run_dir = get_run_dir(session_id)

    try:
        _run_if_needed(run_dir, "cv_tor_mapper", cv_tor_mapper.run, run_dir)

        # Stream A3 alignment warnings onto the polled /manifest channel.
        _emit_warnings(run_dir, session_id, alignment_warnings_for_manifest(run_dir))

        update_step(run_dir, "checkpoint_2", "pending")
        set_checkpoint_pending(session_id, 2)
        log.info("Session %s reached checkpoint_2_pending", session_id)

    except Exception as exc:
        log.exception("Session %s phase 2 failed: %s", session_id, exc)
        set_failed(session_id, str(exc))


# ---------------------------------------------------------------------------
# Phase 3 — Agents 4, 5, 6 (generate → review → compress)
# ---------------------------------------------------------------------------


async def run_phase3(*, session_id: str) -> None:
    """
    Run Agents 4 (Fields Generator), 5 (Content Reviewer), and 6 (Compressor),
    then halt at checkpoint_3_pending.

    The reviewer is non-blocking: high-severity issues are recorded in
    generated_fields.json["review"] and surfaced in GET /review.  The pipeline
    continues to the compressor regardless.  If the user wants to fix issues
    after reviewing the completed output they use POST /field-edit.
    """
    set_processing(session_id)
    run_dir = get_run_dir(session_id)

    try:
        _run_if_needed(run_dir, "fields_generator", fields_generator.run, run_dir)

        # Hard-block validation: halt if Agent 4 produced no usable content.
        # This catches the silent failure mode where the LLM returns a valid
        # schema skeleton with every content field empty.  Overrides the
        # fields_generator manifest step to "failed" so the manifest view
        # accurately reflects the failure point.
        try:
            validate_fields_generator_output(run_dir)
        except PipelineValidationError as val_exc:
            log.error(
                "Session %s Phase 3 halted by validator: %s",
                session_id,
                val_exc,
            )
            update_step(run_dir, "fields_generator", "failed")
            set_failed(session_id, str(val_exc))
            return

        # R5-D: soft-flag quality warnings after A4 (non-blocking)
        for w in check_fields_generator_warnings(run_dir):
            log.info("Session %s soft-flag [%s]: %s", session_id, w["kind"], w["message"])
            append_warning(run_dir, **w)

        # Stream A4 raw generation warnings onto the polled /manifest channel.
        _emit_warnings(run_dir, session_id, generation_warnings_for_manifest(run_dir))

        if get_step_status(run_dir, "content_reviewer") != "done":
            _, passed = content_reviewer.run(run_dir)
            if not passed:
                log.warning(
                    "Session %s content reviewer flagged high-severity issues — "
                    "continuing to compressor (non-blocking mode)",
                    session_id,
                )

        # R5-D: soft-flag quality warnings after A5 (non-blocking)
        for w in check_content_reviewer_warnings(run_dir):
            log.info("Session %s soft-flag [%s]: %s", session_id, w["kind"], w["message"])
            append_warning(run_dir, **w)

        # Stream A5 review-findings summary onto the polled /manifest channel.
        _emit_warnings(run_dir, session_id, review_summary_for_manifest(run_dir))

        await _run_compressor_and_halt(session_id, run_dir)

    except Exception as exc:
        log.exception("Session %s phase 3 failed: %s", session_id, exc)
        set_failed(session_id, str(exc))


async def run_phase3_resume(*, session_id: str) -> None:
    """
    Resume Phase 3 from the compressor after the reviewer block is resolved.
    Called by the /resolve endpoint.
    """
    set_processing(session_id)
    run_dir = get_run_dir(session_id)

    try:
        await _run_compressor_and_halt(session_id, run_dir)
    except Exception as exc:
        log.exception("Session %s phase 3 resume failed: %s", session_id, exc)
        set_failed(session_id, str(exc))


def _build_field_editor_context(run_dir: Path, row: dict) -> tuple[str, dict]:
    """
    Build the donor string and cv_context dict for the field editor.

    Returns (donor, cv_context) where:
      donor      — normalised format string ("giz" or "world_bank")
      cv_context — {"proposed_position": str, "top_projects": list[str]}
                   top_projects is capped at 3 entries (project_name only)
    """
    donor = (row.get("target_format") or "giz").strip().lower().replace(" ", "_")

    # Load generated data for the cv_context snippet
    gf_path = run_dir / "generated_fields.json"
    cv_context: dict = {"proposed_position": "", "top_projects": []}
    if gf_path.exists():
        try:
            gf = json.loads(gf_path.read_text(encoding="utf-8"))
            generated = gf.get("generated", {})
            proposed = generated.get("proposed_position", "") or ""
            # Cap proposed_position length to avoid bloating the prompt
            if len(proposed) > 150:
                proposed = proposed[:147] + "..."
            cv_context["proposed_position"] = proposed
            projects = generated.get("relevant_projects", [])
            cv_context["top_projects"] = [
                p.get("project_name", "")
                for p in projects[:3]
                if p.get("project_name")
            ]
        except Exception:
            pass  # context is advisory — failure should not block edits

    return donor, cv_context


def run_field_editor_task(*, session_id: str, edits: list[dict]) -> tuple[list[dict], list[dict], str]:
    """
    Apply user-directed field edits to generated_fields.json and transition
    the session to checkpoint_3_pending.

    This is a synchronous function called directly by the POST /field-edit
    handler (not as a BackgroundTask) so the HTTP response can include the
    applied/skipped lists.

    The caller is responsible for:
      - calling increment_round() before invoking this function
      - setting DB status to 'processing' before invoking (set_processing)
      - transitioning to checkpoint_3_pending after this returns

    Raises on hard failure; caller should catch and call set_failed().

    Returns
    -------
    applied : list[dict]
        Applied edit records (path, instruction, previous/new previews).
    skipped : list[dict]
        Each item is {"path": str, "reason": str} — passthrough from
        field_editor.run().  Reason is capped at 200 chars.
    kq_source : str
        API-facing label for the active KQ source after edits are applied.
        One of ``"ai_generated"``, ``"extracted"``, or ``"absent"``.
    """
    run_dir = get_run_dir(session_id)
    row = get_session_row(session_id) or {}

    # P5: build donor and cv_context for field editor context enrichment
    donor, cv_context = _build_field_editor_context(run_dir, row)

    applied, skipped, kq_source = field_editor.run(
        run_dir, edits, donor=donor, cv_context=cv_context
    )

    # Reset checkpoint_3 and renderer manifest steps so Phase 4 will re-run
    # on the next POST /approve/checkpoint_3.
    update_step(run_dir, "checkpoint_3", "pending")
    update_step(run_dir, "renderer", "waiting")

    set_checkpoint_pending(session_id, 3)
    log.info(
        "Session %s field_editor complete — applied=%s skipped=%s kq_source=%s → checkpoint_3_pending",
        session_id,
        applied,
        skipped,
        kq_source,
    )
    return applied, skipped, kq_source


async def _run_compressor_and_halt(session_id: str, run_dir: Path) -> None:
    """Shared helper: run the compressor, then halt at checkpoint 3."""

    # Resolve compression target from page_limit or fallback ratio (format-specific)
    from templates.registry import get_compression_params

    row = get_session_row(session_id) or {}
    target_format = row.get("target_format", "giz")
    cp = get_compression_params(target_format, session_id)
    _run_if_needed(
        run_dir,
        "compressor",
        compressor.run,
        run_dir,
        target_words=cp["target_words"],
        compression_ratio=cp["compression_ratio"],
    )

    # R5-D: soft-flag quality warnings after A6 (non-blocking)
    for w in check_compressor_warnings(run_dir):
        log.info("Session %s soft-flag [%s]: %s", session_id, w["kind"], w["message"])
        append_warning(run_dir, **w)

    update_step(run_dir, "checkpoint_3", "pending")
    set_checkpoint_pending(session_id, 3)
    log.info("Session %s reached checkpoint_3_pending", session_id)


# ---------------------------------------------------------------------------
# Phase 4 — Renderer
# ---------------------------------------------------------------------------


async def run_phase4(*, session_id: str) -> None:
    """
    Run the renderer for the session's target format, upload output.docx to
    Supabase Storage, and set the session to completed.
    """
    set_processing(session_id)
    run_dir = get_run_dir(session_id)

    try:
        # Avoid concurrent duplicate Phase 4 tasks only — do NOT skip when status is
        # still "done" from a previous completed render: field edits reset the
        # manifest to "waiting", but if that write ever races or stalls, we would
        # skip re-rendering and leave output.docx stale while JSON was updated.
        if get_step_status(run_dir, "renderer") == "running":
            log.warning("Session %s renderer already running — skipping duplicate Phase 4", session_id)
            return

        update_step(run_dir, "renderer", "running")

        row = get_session_row(session_id) or {}
        target_format = row.get("target_format", "giz")

        from templates.registry import get_renderer

        output_path = get_renderer(target_format)(session_id)

        update_step(run_dir, "renderer", "done")

        # Upload output.docx to Supabase Storage
        round_num = int(row.get("round") or 1)

        output_key = build_object_path(
            session_id,
            "output",
            f"round_{round_num:02d}_{target_format}.docx",
        )
        output_bytes = output_path.read_bytes()
        upload_bytes(
            object_path=output_key,
            data=output_bytes,
            content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
        )
        update_session_storage_keys(session_id, output_storage_key=output_key)
        set_done(session_id, output_key)

        log.info("Session %s completed — output at %s", session_id, output_key)

    except Exception as exc:
        import contextlib

        log.exception("Session %s phase 4 (renderer) failed: %s", session_id, exc)
        with contextlib.suppress(Exception):
            update_step(run_dir, "renderer", "failed")
        set_failed(session_id, str(exc))
