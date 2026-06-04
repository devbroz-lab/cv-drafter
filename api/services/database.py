"""Supabase database helpers for session persistence."""

from __future__ import annotations

import importlib
import logging
from datetime import UTC, datetime
from typing import Any

from api.config import settings

log = logging.getLogger(__name__)

_client: Any | None = None


def get_service_client() -> Any:
    global _client
    if _client is None:
        try:
            supabase_module = importlib.import_module("supabase")
            create_client = supabase_module.create_client
        except ImportError as exc:
            raise RuntimeError(
                "Supabase client not installed. "
                'Run `pip install -e ".[dev]"` using Python 3.12.13.'
            ) from exc
        _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _client


def create_session_row(
    *,
    user_id: str,
    target_format: str,
    source_filename: str,
    tor_filename: str | None = None,
    category: str | None = None,
    employer: str | None = None,
    years_with_firm: str | None = None,
    page_limit: int | None = None,
    job_description: str | None = None,
    recruiter_comments: str | None = None,
) -> dict[str, Any]:
    # proposed_position is intentionally absent here — it is derived from the
    # selected ToR pool's position_title at checkpoint_1 (POST /tor/select-pool)
    # and written to the DB row at that point.
    payload: dict[str, Any] = {
        "user_id": user_id,
        "target_format": target_format,
        "source_filename": source_filename,
        "status": "queued",
        "round": 1,
    }
    if tor_filename:
        payload["tor_filename"] = tor_filename
    if category:
        payload["category"] = category
    if employer:
        payload["employer"] = employer
    if years_with_firm:
        payload["years_with_firm"] = years_with_firm
    if page_limit is not None:
        payload["page_limit"] = page_limit
    if job_description:
        payload["job_description"] = job_description
    if recruiter_comments is not None:
        payload["recruiter_comments"] = recruiter_comments

    result = get_service_client().table("sessions").insert(payload).execute()
    if not result.data:
        raise RuntimeError("Supabase insert returned no session row")
    return result.data[0]


def list_sessions_for_user(
    user_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return sessions owned by the user, newest activity first."""
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)
    result = (
        get_service_client()
        .table("sessions")
        .select(
            "id, status, target_format, round, source_filename, created_at, updated_at"
        )
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .range(safe_offset, safe_offset + safe_limit - 1)
        .execute()
    )
    return list(result.data or [])


def get_session_row(
    session_id: str,
    *,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    query = get_service_client().table("sessions").select("*").eq("id", session_id)
    if user_id is not None:
        query = query.eq("user_id", user_id)
    result = query.limit(1).execute()
    if not result.data:
        return None
    return result.data[0]


def update_session_row(
    session_id: str,
    *,
    status: str,
    user_id: str | None = None,
    output_file_path: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {"status": status}
    if output_file_path is not None:
        payload["output_file_path"] = output_file_path
    if error_message is not None:
        payload["error_message"] = error_message

    query = get_service_client().table("sessions").update(payload).eq("id", session_id)
    if user_id is not None:
        query = query.eq("user_id", user_id)
    result = query.execute()
    if not result.data:
        return None
    return result.data[0]


# ── Named status helpers ───────────────────────────────────────────────────────
# These wrap update_session_row() with explicit semantics so callers (orchestrator,
# background tasks) never pass raw status strings around.


def set_processing(session_id: str) -> None:
    """Transition a session to 'processing' and clear any previous error."""
    update_session_row(session_id, status="processing", error_message="")


def set_done(session_id: str, output_storage_path: str) -> None:
    """Transition a session to 'completed' and record the output storage key."""
    update_session_row(
        session_id,
        status="completed",
        output_file_path=output_storage_path,
    )
    try:
        from api.services.metering import commit_pipeline_run

        commit_pipeline_run(session_id=session_id)
    except Exception:
        log.exception("Metering commit failed for session %s", session_id)


def set_failed(session_id: str, error_message: str) -> None:
    """Transition a session to 'failed' and record the error reason."""
    update_session_row(session_id, status="failed", error_message=error_message)
    try:
        from api.services.metering import release_pipeline_reserve

        release_pipeline_reserve(session_id)
    except Exception:
        log.exception("Metering release failed for session %s", session_id)


def increment_round(session_id: str) -> int:
    """
    Atomically increment the round counter for a session.

    Reads the current value, writes current + 1, and returns the NEW round number.
    Safe for single-tenant background task use — not intended for concurrent callers.
    """
    row = get_session_row(session_id)
    current = int((row or {}).get("round") or 1)
    new_round = current + 1
    (
        get_service_client()
        .table("sessions")
        .update({"round": new_round})
        .eq("id", session_id)
        .execute()
    )
    return new_round


def count_active_sessions(user_id: str) -> int:
    """
    Return the number of sessions for this user that are in any active state
    (queued, processing, or any checkpoint/blocked state).

    Used by POST /sessions to enforce a per-user concurrency cap (max 3 active
    sessions) to prevent runaway Anthropic API costs.
    """
    active_statuses = [
        "queued",
        "processing",
        "checkpoint_1_pending",
        "checkpoint_2_pending",
        "reviewer_blocked",
        "field_editor_pending",
        "checkpoint_3_pending",
    ]
    result = (
        get_service_client()
        .table("sessions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .in_("status", active_statuses)
        .execute()
    )
    return result.count or 0


def set_checkpoint_pending(session_id: str, checkpoint_num: int) -> None:
    """
    Transition a session to the checkpoint_N_pending state.
    Called by the orchestrator when it halts at a human checkpoint.
    """
    status = f"checkpoint_{checkpoint_num}_pending"
    update_session_row(session_id, status=status)


def set_reviewer_blocked(session_id: str) -> None:
    """
    Transition a session to reviewer_blocked.
    Called when Agent 5 (Content Reviewer) flags high-severity issues.
    """
    update_session_row(session_id, status="reviewer_blocked")


def set_field_editor_pending(session_id: str) -> None:
    """
    Transition a session to field_editor_pending.
    Called after the preview render completes, before the field_editor agent runs.
    """
    update_session_row(session_id, status="field_editor_pending")


def reset_stale_processing_sessions() -> int:
    """
    On server startup, find sessions stuck in *processing* and mark them failed.

    A checkpoint_*_pending or reviewer_blocked session is intentionally idle
    waiting for a human — restarting the API must not destroy that work.

    Only *processing* means a background task may have been cut off mid-flight
    (reload, crash, deploy), which would otherwise leave a permanent ghost run.

    Does NOT reset: queued, checkpoint_*_pending, reviewer_blocked, completed, failed.

    Returns the number of sessions reset.
    """
    stale_statuses = [
        "processing",
        "field_editor_pending",
    ]
    total = 0
    for stale_status in stale_statuses:
        stale_rows = (
            get_service_client()
            .table("sessions")
            .select("id")
            .eq("status", stale_status)
            .execute()
        )
        stale_ids = [str(r["id"]) for r in (stale_rows.data or [])]
        result = (
            get_service_client()
            .table("sessions")
            .update({"status": "failed", "error_message": "Server restarted during processing"})
            .eq("status", stale_status)
            .execute()
        )
        total += len(result.data) if result.data else 0
        if stale_ids:
            try:
                from api.services.metering import release_pipeline_reserve

                for session_id in stale_ids:
                    release_pipeline_reserve(session_id)
            except Exception:
                log.exception("Metering release failed during stale session recovery")
    if total:
        log.warning("Startup recovery: reset %d stale session(s) to failed", total)
    return total


# ── Storage key helper ────────────────────────────────────────────────────────


def update_session_storage_keys(
    session_id: str,
    *,
    user_id: str | None = None,
    source_storage_key: str | None = None,
    tor_storage_key: str | None = None,
    output_storage_key: str | None = None,
    source_filename: str | None = None,
    tor_filename: str | None = None,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    if source_storage_key is not None:
        payload["source_storage_key"] = source_storage_key
    if tor_storage_key is not None:
        payload["tor_storage_key"] = tor_storage_key
    if output_storage_key is not None:
        payload["output_storage_key"] = output_storage_key
    if source_filename is not None:
        payload["source_filename"] = source_filename
    if tor_filename is not None:
        payload["tor_filename"] = tor_filename
    if not payload:
        return get_session_row(session_id, user_id=user_id)

    query = get_service_client().table("sessions").update(payload).eq("id", session_id)
    if user_id is not None:
        query = query.eq("user_id", user_id)
    result = query.execute()
    if not result.data:
        return None
    return result.data[0]


# ── App auth helpers (additive tables) ────────────────────────────────────────


def get_app_user_by_email(email: str) -> dict[str, Any] | None:
    result = (
        get_service_client()
        .table("app_users")
        .select("*")
        .eq("email", email.lower())
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


def get_app_user_by_id(user_id: str) -> dict[str, Any] | None:
    result = get_service_client().table("app_users").select("*").eq("id", user_id).limit(1).execute()
    if not result.data:
        return None
    return result.data[0]


def create_app_user(
    *,
    email: str,
    password_hash: str | None,
    google_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "email": email.lower(),
        "password_hash": password_hash,
        "google_id": google_id,
    }
    result = get_service_client().table("app_users").insert(payload).execute()
    if not result.data:
        raise RuntimeError("Supabase insert returned no app_users row")
    user = result.data[0]
    try:
        from api.services.metering import provision_new_user

        provision_new_user(str(user["id"]))
    except Exception:
        log.exception("Failed to provision metering for user %s", user.get("id"))
    return user


def update_app_user(user_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
    result = get_service_client().table("app_users").update(values).eq("id", user_id).execute()
    if not result.data:
        return None
    return result.data[0]


def save_refresh_token(*, user_id: str, token: str, expires_at_iso: str) -> None:
    payload = {
        "user_id": user_id,
        "token": token,
        "expires_at": expires_at_iso,
    }
    get_service_client().table("app_refresh_tokens").insert(payload).execute()


def find_valid_refresh_token(token: str) -> dict[str, Any] | None:
    now_iso = datetime.now(UTC).isoformat()
    result = (
        get_service_client()
        .table("app_refresh_tokens")
        .select("*")
        .eq("token", token)
        .gt("expires_at", now_iso)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


def delete_refresh_token(token: str) -> None:
    get_service_client().table("app_refresh_tokens").delete().eq("token", token).execute()
