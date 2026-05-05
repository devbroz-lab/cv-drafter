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

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from api.services.database import (
    get_session_row,
    set_checkpoint_pending,
    set_done,
    set_failed,
    set_field_editor_pending,
    set_processing,
    update_session_storage_keys,
)
from api.services.storage import build_object_path, download_bytes, upload_bytes

from pipeline.agents import (
    compressor,
    content_reviewer,
    cv_extractor,
    cv_tor_mapper,
    fields_generator,
    tor_summarizer,
)
from pipeline.extractor import extract_text
from pipeline.manifest import create_manifest, get_step_status, update_step
from pipeline.paths import RUNS_ROOT, get_preview_docx_path, get_run_dir

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
    Run Agents 4 (Fields Generator) and 5 (Content Reviewer), render preview.docx,
    then halt at field_editor_pending.

    The reviewer is non-blocking: high-severity issues are recorded in
    generated_fields.json and surfaced to the user as informational context
    during the field_editor_pending review step.

    The preview render is non-fatal: if it fails the session still advances to
    field_editor_pending so the user can submit edits (the viewer will show an
    error when trying to load the preview).

    The pipeline resumes when the user submits edits via POST /field-edit,
    which calls run_phase3_after_field_editor() to run Agent 7 + compressor.
    """
    set_processing(session_id)
    run_dir = get_run_dir(session_id)

    try:
        _run_if_needed(run_dir, "fields_generator", fields_generator.run, run_dir)

        if get_step_status(run_dir, "content_reviewer") != "done":
            _, passed = content_reviewer.run(run_dir)
            if not passed:
                log.warning(
                    "Session %s content reviewer flagged high-severity issues — "
                    "continuing to field_editor_pending (non-blocking mode)",
                    session_id,
                )

        # ── Preview render (non-fatal) ────────────────────────────────────
        row = get_session_row(session_id) or {}
        target_format = row.get("target_format", "giz")
        preview_path = get_preview_docx_path(session_id)
        try:
            from templates.registry import get_renderer
            get_renderer(target_format)(session_id, output_path=preview_path)
            log.info("Session %s preview render complete → %s", session_id, preview_path)
        except Exception as preview_exc:
            log.warning(
                "Session %s preview render failed (non-fatal, continuing to "
                "field_editor_pending): %s",
                session_id,
                preview_exc,
            )

        # ── Halt at field_editor_pending ──────────────────────────────────
        update_step(run_dir, "field_editor", "pending")
        set_field_editor_pending(session_id)
        log.info("Session %s reached field_editor_pending", session_id)

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


async def run_phase3_after_field_editor(*, session_id: str) -> None:
    """
    Run the compressor and halt at checkpoint_3 after field_editor completes.

    Scheduled as a FastAPI BackgroundTask by the POST /field-edit endpoint
    immediately after field_editor.run() returns synchronously.  The DB status
    is already set to 'processing' by the HTTP handler before this task runs.
    """
    run_dir = get_run_dir(session_id)

    try:
        await _run_compressor_and_halt(session_id, run_dir)
    except Exception as exc:
        log.exception(
            "Session %s phase 3 (post field_editor) failed: %s", session_id, exc
        )
        set_failed(session_id, str(exc))


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
        # Idempotency guard — never render twice
        if get_step_status(run_dir, "renderer") == "done":
            log.warning("Session %s renderer already done — skipping", session_id)
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
