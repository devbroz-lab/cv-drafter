"""
Pipeline boundary — LOCKED signatures.  [BOUNDARY]

These two functions are the sole public interface between the orchestrator
and the agent pipeline.  Their names and parameter lists are frozen.

run_pipeline()  — called by POST /sessions/{id}/start background task
run_revision()  — called by POST /sessions/{id}/comments background task

Dev 2 / Dev 3:  You may only replace the BODY of these functions.
                Never rename them, never add or remove parameters.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.orchestrator import run_phase1, run_phase3_resume


async def run_pipeline(
    input_path: Path,
    target_format: str,
    page_limit: int | None,
    tor_text: str,
    job_description: str,
    recruiter_comments: str,
) -> Path:
    """
    Entry point for a new CV reformatting run.

    This function is called by the orchestrator's process_session() background
    task immediately after the user triggers POST /sessions/{id}/start.

    It delegates to run_phase1() which:
      1. Downloads the source CV from Supabase Storage.
      2. Extracts text via pipeline/extractor.
      3. Runs Agents 1 & 2 in parallel (cv_extractor + tor_summarizer).
      4. Writes cv_data.json and tor_data.json to runs/{session_id}/.
      5. Halts at checkpoint_1_pending — no output file yet.

    The pipeline continues through phases 2-4 only after the user approves
    each checkpoint via POST /sessions/{id}/approve/{checkpoint}.

    Parameters
    ----------
    input_path:
        Absolute path to the downloaded source CV file (.docx or .pdf).
        Written by process_session() before calling this function.
        Deleted by process_session() after this function returns.
    target_format:
        ``"giz"`` or ``"world_bank"``.
    page_limit:
        Maximum output pages, or None if unconstrained.
    tor_text:
        Full plain-text content of the ToR document, or "" if none.
    job_description:
        Free-text job description, or "".
    recruiter_comments:
        Accumulated recruiter feedback, or "" on the first run.

    Returns
    -------
    Path
        The function is required to return a Path by the locked signature.
        During Phase 1 the output file does not yet exist, so we return
        input_path as a placeholder.  The real output.docx is produced and
        uploaded by run_phase4() after checkpoint_3 approval.
    """
    # Phase 1 is called directly by process_session() in orchestrator.py,
    # which passes all session context.  This function exists to honour the
    # locked boundary contract; the real work happens in orchestrator.run_phase1().
    #
    # If called standalone (e.g. in tests), derive session_id from the run dir.
    session_id = input_path.parent.parent.name  # runs/{session_id}/input/{file}
    from api.services.database import get_session_row

    row = get_session_row(session_id) or {}
    source_storage_key = row.get("source_storage_key", "")
    tor_storage_key = row.get("tor_storage_key")
    source_filename = row.get("source_filename", input_path.name)

    await run_phase1(
        session_id=session_id,
        source_storage_key=source_storage_key,
        source_filename=source_filename,
        target_format=target_format,
        tor_storage_key=tor_storage_key,
    )

    # Return input_path as the placeholder — process_session() will clean it up.
    return input_path


async def run_revision(
    session_id: str,
    new_comment: str,
    target_format: str,
    page_limit: int | None,
    tor_text: str,
    job_description: str,
) -> Path:
    """
    Entry point for a revision run triggered by POST /sessions/{id}/comments.

    A revision re-runs Phase 3 (Fields Generator → Content Reviewer → Compressor)
    with the updated recruiter_comments already persisted on the DB row, then
    halts at checkpoint_3_pending for final approval before re-rendering.

    Parameters
    ----------
    session_id:
        UUID of the session being revised.
    new_comment:
        The full accumulated recruiter_comments string (already updated in DB
        by the /comments endpoint before this function is called).
    target_format:
        ``"giz"`` or ``"world_bank"``.
    page_limit:
        Maximum output pages, or None.
    tor_text:
        Full plain-text ToR content, or "".
    job_description:
        Free-text job description, or "".

    Returns
    -------
    Path
        Placeholder path (output is produced and uploaded by run_phase4()).
    """
    await run_phase3_resume(session_id=session_id)

    # Return a placeholder — actual output is uploaded by run_phase4.
    from pipeline.paths import get_run_dir

    run_dir = get_run_dir(session_id)
    placeholder = run_dir / "output.docx"
    return placeholder if placeholder.exists() else run_dir
