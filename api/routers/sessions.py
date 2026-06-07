"""Session lifecycle endpoints backed by Supabase."""

import json
import logging
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pipeline.text_encoding import UTF_8
from pipeline.utils import load_tor_envelope, resolve_selected_tor_pool

from api.models.requests import (
    CHECKPOINT_RESUME_MAP,
    CHECKPOINT_STATUS_MAP,
    ApproveRequest,
    ApproveResponse,
    CommentsRequest,
    CommentsResponse,
    FieldEditRequest,
    FieldEditResponse,
    FileUploadResponse,
    ManifestResponse,
    ManifestStepResponse,
    OutputResponse,
    ResolveRequest,
    ResolveResponse,
    ReviewResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionListResponse,
    SessionStartResponse,
    SessionStatusResponse,
    SessionSummary,
    SessionStatusUpdateRequest,
    SignedDownloadResponse,
    TorPoolSelectionRequest,
    TorPoolSelectionResponse,
    TorPoolsResponse,
    WarningEntry,
    WarningsResponse,
)
from api.services import storage as storage_service
from api.services.auth import AuthenticatedUser, get_current_user
from api.services.database import (
    count_active_sessions,
    create_session_row,
    get_session_row,
    list_sessions_for_user,
    increment_round,
    set_failed,
    set_processing,
    update_session_row,
    update_session_storage_keys,
)
from api.services.dot_path import DotPathError, set_by_dot_path

log = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]

# File types accepted for source CV uploads.
_ALLOWED_EXTENSIONS = {".docx", ".pdf"}
# Maximum concurrent active sessions per user (queued + processing).
_MAX_ACTIVE_SESSIONS = 3


# ── Helpers ───────────────────────────────────────────────────────────────────



def _row_to_summary(row: dict[str, Any]) -> SessionSummary:
    return SessionSummary(
        session_id=row["id"],
        status=row["status"],
        target_format=row["target_format"],
        round=row.get("round") or 1,
        source_filename=row["source_filename"],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _row_to_status(row: dict[str, Any]) -> SessionStatusResponse:
    return SessionStatusResponse(
        session_id=row["id"],
        user_id=row.get("user_id"),
        status=row["status"],
        target_format=row["target_format"],
        round=row.get("round") or 1,
        source_filename=row["source_filename"],
        tor_filename=row.get("tor_filename"),
        source_storage_key=row.get("source_storage_key"),
        tor_storage_key=row.get("tor_storage_key"),
        output_storage_key=row.get("output_storage_key"),
        output_file_path=row.get("output_file_path"),
        error_message=row.get("error_message") or None,
        page_limit=row.get("page_limit"),
        job_description=row.get("job_description"),
        recruiter_comments=row.get("recruiter_comments"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _require_owned_session(session_id: str, user_id: str) -> dict[str, Any]:
    row = get_session_row(session_id, user_id=user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return row


def _validate_cv_extension(filename: str | None) -> None:
    """Raise 400 if the filename does not have an allowed CV extension."""
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{suffix}'. Only .docx and .pdf are accepted.",
        )


# ── GET /sessions ─────────────────────────────────────────────────────────────


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SessionListResponse:
    """List sessions for the authenticated user (newest first)."""
    try:
        rows = list_sessions_for_user(current_user.user_id, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    return SessionListResponse(sessions=[_row_to_summary(row) for row in rows])


# ── POST /sessions ────────────────────────────────────────────────────────────


@router.post("", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreateRequest,
    current_user: CurrentUser,
) -> SessionCreateResponse:
    # Rate limit: block users who already have too many active sessions.
    try:
        active = count_active_sessions(current_user.user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not check active session count: {exc}",
        ) from exc

    if active >= _MAX_ACTIVE_SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"You already have {active} active session(s). "
                f"Wait for them to complete before starting a new one."
            ),
        )

    try:
        row = create_session_row(
            user_id=current_user.user_id,
            target_format=payload.target_format,
            source_filename=payload.source_filename,
            tor_filename=payload.tor_filename,
            category=payload.category,
            employer=payload.employer,
            years_with_firm=payload.years_with_firm,
            page_limit=payload.page_limit,
            job_description=payload.job_description,
            recruiter_comments=payload.recruiter_comments or "",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    return SessionCreateResponse(session_id=row["id"], status=row["status"])


# ── GET /sessions/{id}/status ─────────────────────────────────────────────────


@router.get("/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(
    session_id: str,
    current_user: CurrentUser,
) -> SessionStatusResponse:
    try:
        row = get_session_row(session_id, user_id=current_user.user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    resp = _row_to_status(row)

    # Generate a fresh signed download URL when the output is ready.
    if row["status"] == "completed" and row.get("output_storage_key"):
        import contextlib

        with contextlib.suppress(Exception):
            resp.download_url = storage_service.create_signed_download_url(
                object_path=row["output_storage_key"],
                expires_in=3600,
            )

    return resp


# ── PATCH /sessions/{id}/status ───────────────────────────────────────────────


@router.patch("/{session_id}/status", response_model=SessionStatusResponse)
async def update_session_status(
    session_id: str,
    payload: SessionStatusUpdateRequest,
    current_user: CurrentUser,
) -> SessionStatusResponse:
    try:
        row = update_session_row(
            session_id,
            status=payload.status,
            user_id=current_user.user_id,
            output_file_path=payload.output_file_path,
            error_message=payload.error_message,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    return _row_to_status(row)


# ── POST /sessions/{id}/upload/source ────────────────────────────────────────


@router.post(
    "/{session_id}/upload/source",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source_cv(
    session_id: str,
    current_user: CurrentUser,
    file: UploadFile = File(...),  # noqa: B008
    expires_seconds: int = Query(default=3600, ge=60, le=604800),
) -> FileUploadResponse:
    row = _require_owned_session(session_id, current_user.user_id)
    if row["status"] != "queued":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source upload allowed only while session is queued",
        )

    # Validate file type — only .docx and .pdf accepted.
    _validate_cv_extension(file.filename)

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    object_path = storage_service.build_object_path(
        session_id, "source", file.filename or "source.bin"
    )
    try:
        storage_service.upload_bytes(
            object_path=object_path,
            data=data,
            content_type=file.content_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    updated = update_session_storage_keys(
        session_id,
        user_id=current_user.user_id,
        source_storage_key=object_path,
        source_filename=file.filename or row["source_filename"],
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update session with source storage key",
        )

    signed = storage_service.create_signed_download_url(
        object_path=object_path, expires_in=expires_seconds
    )
    return FileUploadResponse(
        storage_key=object_path, signed_url=signed, expires_in=expires_seconds
    )


# ── POST /sessions/{id}/upload/tor ───────────────────────────────────────────


@router.post(
    "/{session_id}/upload/tor",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_terms_of_reference(
    session_id: str,
    current_user: CurrentUser,
    file: UploadFile = File(...),  # noqa: B008
    expires_seconds: int = Query(default=3600, ge=60, le=604800),
) -> FileUploadResponse:
    row = _require_owned_session(session_id, current_user.user_id)
    if row["status"] != "queued":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ToR upload allowed only while session is queued",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    object_path = storage_service.build_object_path(session_id, "tor", file.filename or "tor.bin")
    try:
        storage_service.upload_bytes(
            object_path=object_path,
            data=data,
            content_type=file.content_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    tor_kwargs: dict[str, str] = {"tor_storage_key": object_path}
    if file.filename:
        tor_kwargs["tor_filename"] = file.filename
    updated = update_session_storage_keys(session_id, user_id=current_user.user_id, **tor_kwargs)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update session with ToR storage key",
        )

    signed = storage_service.create_signed_download_url(
        object_path=object_path, expires_in=expires_seconds
    )
    return FileUploadResponse(
        storage_key=object_path, signed_url=signed, expires_in=expires_seconds
    )


# ── Signed URL endpoints ──────────────────────────────────────────────────────


@router.get("/{session_id}/files/source/download-url", response_model=SignedDownloadResponse)
async def signed_url_for_source(
    session_id: str,
    current_user: CurrentUser,
    expires_seconds: int = Query(default=3600, ge=60, le=604800),
) -> SignedDownloadResponse:
    row = _require_owned_session(session_id, current_user.user_id)
    key = row.get("source_storage_key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source file not uploaded yet"
        )
    try:
        signed = storage_service.create_signed_download_url(
            object_path=key, expires_in=expires_seconds
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return SignedDownloadResponse(signed_url=signed, expires_in=expires_seconds)


@router.get("/{session_id}/files/tor/download-url", response_model=SignedDownloadResponse)
async def signed_url_for_tor(
    session_id: str,
    current_user: CurrentUser,
    expires_seconds: int = Query(default=3600, ge=60, le=604800),
) -> SignedDownloadResponse:
    row = _require_owned_session(session_id, current_user.user_id)
    key = row.get("tor_storage_key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ToR file not uploaded yet"
        )
    try:
        signed = storage_service.create_signed_download_url(
            object_path=key, expires_in=expires_seconds
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return SignedDownloadResponse(signed_url=signed, expires_in=expires_seconds)


@router.get("/{session_id}/files/output/download-url", response_model=SignedDownloadResponse)
async def signed_url_for_output(
    session_id: str,
    current_user: CurrentUser,
    expires_seconds: int = Query(default=3600, ge=60, le=604800),
) -> SignedDownloadResponse:
    row = _require_owned_session(session_id, current_user.user_id)
    key = row.get("output_storage_key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Output file not available yet"
        )
    try:
        signed = storage_service.create_signed_download_url(
            object_path=key, expires_in=expires_seconds
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return SignedDownloadResponse(signed_url=signed, expires_in=expires_seconds)


@router.get("/{session_id}/files/preview", response_class=None)
async def get_preview_docx(
    session_id: str,
    current_user: CurrentUser,
) -> Any:
    """
    Stream runs/{session_id}/preview.docx directly.

    preview.docx is a local-only artifact.  It is never uploaded to Supabase
    Storage, so it cannot be served via a signed URL — it is streamed directly
    from disk.  Only available if a preview file was produced for this session.
    """
    from fastapi.responses import FileResponse

    _require_owned_session(session_id, current_user.user_id)

    from pipeline.paths import get_run_dir

    run_dir = get_run_dir(session_id)
    preview_path = run_dir / "preview.docx"
    if not preview_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="preview.docx not available for this session",
        )
    return FileResponse(
        path=str(preview_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="preview.docx",
    )


# ── POST /sessions/{id}/start ─────────────────────────────────────────────────


@router.post("/{session_id}/start", response_model=SessionStartResponse)
async def start_session_processing(
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
) -> SessionStartResponse:
    row = _require_owned_session(session_id, current_user.user_id)

    if row["status"] != "queued":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only queued sessions can be started",
        )
    if not row.get("source_storage_key"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source file must be uploaded before starting",
        )

    from api.services.metering import InsufficientCreditsError, reserve_pipeline_run
    from api.services.metering.http import raise_insufficient_credits

    try:
        reserve_pipeline_run(user_id=current_user.user_id, session_id=session_id)
    except InsufficientCreditsError as exc:
        raise_insufficient_credits(exc)

    from pipeline.orchestrator import run_phase1

    background_tasks.add_task(
        run_phase1,
        session_id=session_id,
        source_storage_key=row["source_storage_key"],
        tor_storage_key=row.get("tor_storage_key"),
        target_format=row["target_format"],
        source_filename=row["source_filename"],
    )

    return SessionStartResponse(
        session_id=session_id,
        status="processing",
        message="Processing started in the background",
    )


# ── POST /sessions/{id}/comments (DEPRECATED) ────────────────────────────────


@router.post("/{session_id}/comments", response_model=CommentsResponse)
async def submit_revision_comment(
    session_id: str,
    payload: CommentsRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    response: Response,
) -> CommentsResponse:
    """
    DEPRECATED — use POST /sessions/{id}/field-edit instead.

    This endpoint re-runs the full Phase 3 agent chain on free-text feedback.
    It is replaced by POST /field-edit which applies targeted, LLM-mediated
    edits directly to specific fields without re-running the pipeline.

    This endpoint remains functional for backward compatibility but will be
    removed in a future release.
    """
    log.warning(
        "DEPRECATED endpoint POST /sessions/%s/comments called. "
        "Use POST /sessions/%s/field-edit instead.",
        session_id,
        session_id,
    )
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-12-31"
    response.headers["Link"] = (
        f'</sessions/{session_id}/field-edit>; rel="successor-version"'
    )

    row = _require_owned_session(session_id, current_user.user_id)

    if row["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Revision comments can only be submitted on completed sessions "
                f"(current status: {row['status']})"
            ),
        )

    # Determine the upcoming round number (increment happens inside background task,
    # but we preview it here for the response).
    current_round = int(row.get("round") or 1)
    next_round = current_round + 1

    # Append the new comment with a round prefix to preserve history.
    existing = (row.get("recruiter_comments") or "").strip()
    tagged_comment = f"[Round {next_round}]: {payload.comment.strip()}"
    updated_comments = f"{existing}\n{tagged_comment}".strip() if existing else tagged_comment

    # Persist the updated comments string NOW so process_revision can read it.
    try:
        update_session_row(
            session_id,
            status="completed",  # keep completed until background task sets processing
            user_id=current_user.user_id,
        )
        # Update recruiter_comments directly via the DB client.
        from api.services.database import get_service_client

        get_service_client().table("sessions").update({"recruiter_comments": updated_comments}).eq(
            "id", session_id
        ).execute()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist comment: {exc}",
        ) from exc

    from pipeline.orchestrator import run_phase3_resume

    background_tasks.add_task(
        run_phase3_resume,
        session_id=session_id,
    )

    return CommentsResponse(
        session_id=session_id,
        status="processing",
        round=next_round,
        message=(
            "Revision queued. Poll /status for updates. "
            "DEPRECATED: use POST /field-edit for targeted edits instead."
        ),
    )


# ── GET /sessions/{id}/manifest ───────────────────────────────────────────────


@router.get("/{session_id}/manifest", response_model=ManifestResponse)
async def get_session_manifest(
    session_id: str,
    current_user: CurrentUser,
) -> ManifestResponse:
    """
    Return the fine-grained step manifest for this session.
    The frontend (ManifestPoller / StepStatusStepper) polls this to drive
    checkpoint UI transitions.
    """
    row = _require_owned_session(session_id, current_user.user_id)

    from pipeline.manifest import load_manifest
    from pipeline.paths import get_run_dir

    from api.services.run_artifacts import hydrate_run_artifact

    run_dir = get_run_dir(session_id)
    hydrate_run_artifact(session_id, run_dir, "manifest.json")
    if not (run_dir / "manifest.json").is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Manifest not found — pipeline has not started yet",
        )

    try:
        manifest = load_manifest(run_dir)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not read manifest: {exc}",
        ) from exc

    steps = [
        ManifestStepResponse(
            name=s["name"],
            status=s["status"],
            completed_at=s.get("completed_at"),
        )
        for s in manifest.get("steps", [])
    ]

    # Determine which checkpoint is currently pending (if any)
    checkpoint_pending = None
    reviewer_blocked = False
    for s in steps:
        if s.name.startswith("checkpoint_") and s.status == "pending":
            checkpoint_pending = s.name
        if s.name == "content_reviewer" and s.status == "blocked":
            reviewer_blocked = True

    return ManifestResponse(
        session_id=session_id,
        db_status=row["status"],
        steps=steps,
        checkpoint_pending=checkpoint_pending,
        reviewer_blocked=reviewer_blocked,
    )


# ── GET /sessions/{id}/tor/pools ──────────────────────────────────────────────


@router.get("/{session_id}/tor/pools", response_model=TorPoolsResponse)
async def get_tor_pools(
    session_id: str,
    current_user: CurrentUser,
) -> TorPoolsResponse:
    """
    Return tor_data pools and selected_pool_index for checkpoint-1 picker UIs.
    """
    row = _require_owned_session(session_id, current_user.user_id)

    from api.services.run_artifacts import hydrate_run_artifact
    from pipeline.paths import get_run_dir

    run_dir = get_run_dir(session_id)
    hydrate_run_artifact(session_id, run_dir, "tor_data.json")
    tor_path = run_dir / "tor_data.json"
    if not tor_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tor_data.json not found — ToR summarizer may not have completed yet",
        )

    try:
        tor_raw = load_tor_envelope(tor_path, context="api.sessions.get_tor_pools")
        pools = tor_raw.get("pools")
        if not isinstance(pools, list) or len(pools) == 0:
            raise ValueError("tor_data.pools must be a non-empty list")
        selected_pool_index = tor_raw.get("selected_pool_index")
        if selected_pool_index is not None:
            if isinstance(selected_pool_index, bool) or not isinstance(selected_pool_index, int):
                raise ValueError("selected_pool_index must be an integer or null")
            if selected_pool_index < 0 or selected_pool_index >= len(pools):
                raise ValueError(
                    f"selected_pool_index {selected_pool_index} out of range "
                    f"for {len(pools)} pool(s)"
                )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load ToR pools: {exc}",
        ) from exc

    return TorPoolsResponse(
        session_id=row["id"],
        pools=pools,
        selected_pool_index=selected_pool_index,
    )


# ── POST /sessions/{id}/tor/select-pool ──────────────────────────────────────


@router.post("/{session_id}/tor/select-pool", response_model=TorPoolSelectionResponse)
async def select_tor_pool(
    session_id: str,
    payload: TorPoolSelectionRequest,
    current_user: CurrentUser,
) -> TorPoolSelectionResponse:
    """Persist selected_pool_index in runs/{session_id}/tor_data.json."""
    row = _require_owned_session(session_id, current_user.user_id)

    from api.services.run_artifacts import hydrate_run_artifact, push_run_artifact
    from pipeline.paths import get_run_dir

    run_dir = get_run_dir(session_id)
    hydrate_run_artifact(session_id, run_dir, "tor_data.json")
    tor_path = run_dir / "tor_data.json"
    if not tor_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="tor_data.json not found — ToR summarizer may not have completed yet",
        )

    try:
        tor_raw = load_tor_envelope(tor_path, context="api.sessions.select_tor_pool")
        pools = tor_raw.get("pools")
        if not isinstance(pools, list) or len(pools) == 0:
            raise ValueError("tor_data.pools must be a non-empty list")

        selected_idx = int(payload.selected_pool_index)
        if selected_idx < 0 or selected_idx >= len(pools):
            raise ValueError(
                f"selected_pool_index {selected_idx} out of range "
                f"for {len(pools)} pool(s)"
            )

        tor_raw["selected_pool_index"] = selected_idx
        tor_path.write_text(json.dumps(tor_raw, indent=2, ensure_ascii=False), encoding=UTF_8)
        push_run_artifact(session_id, tor_path)
        selected_pool = resolve_selected_tor_pool(
            tor_raw,
            context="api.sessions.select_tor_pool",
            allow_legacy_data=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist selected pool: {exc}",
        ) from exc

    # Derive proposed_position from the selected pool's position_title and
    # propagate it to manifest.params, cv_data.json, and the DB session row
    # so that downstream agents (3–6) receive the ToR-confirmed position title.
    position_title: str = selected_pool.get("position_title") or ""
    if position_title:
        # Patch manifest.params.proposed_position
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            try:
                _manifest = json.loads(manifest_path.read_text(encoding=UTF_8))
                _manifest.setdefault("params", {})["proposed_position"] = position_title
                manifest_path.write_text(
                    json.dumps(_manifest, indent=2, ensure_ascii=False), encoding=UTF_8
                )
            except Exception:
                pass  # non-fatal — agents fall back to CVData value

        # Patch cv_data.json["data"]["proposed_position"]
        cv_data_path = run_dir / "cv_data.json"
        if cv_data_path.exists():
            try:
                _cv = json.loads(cv_data_path.read_text(encoding=UTF_8))
                _cv.setdefault("data", {})["proposed_position"] = position_title
                cv_data_path.write_text(
                    json.dumps(_cv, indent=2, ensure_ascii=False), encoding=UTF_8
                )
            except Exception:
                pass  # non-fatal

        # Patch DB sessions.proposed_position
        try:
            from api.services.database import get_service_client
            get_service_client().table("sessions").update(
                {"proposed_position": position_title}
            ).eq("id", session_id).execute()
        except Exception:
            pass  # non-fatal

    return TorPoolSelectionResponse(
        session_id=row["id"],
        selected_pool_index=selected_idx,
        pool_count=len(pools),
        position_title=position_title or None,
        message="ToR pool selection saved.",
    )


# ── POST /sessions/{id}/approve/{checkpoint} ──────────────────────────────────


@router.post("/{session_id}/approve/{checkpoint}", response_model=ApproveResponse)
async def approve_checkpoint(
    session_id: str,
    checkpoint: str,
    payload: ApproveRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
) -> ApproveResponse:
    """
    Approve a pipeline checkpoint and schedule the next phase as a background task.

    checkpoint must be one of: checkpoint_1, checkpoint_2, checkpoint_3
    """
    if checkpoint not in CHECKPOINT_STATUS_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown checkpoint '{checkpoint}'. "
            f"Valid values: {list(CHECKPOINT_STATUS_MAP.keys())}",
        )

    row = _require_owned_session(session_id, current_user.user_id)
    expected_status = CHECKPOINT_STATUS_MAP[checkpoint]

    if row["status"] != expected_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Session is not at '{checkpoint}' " f"(current status: {row['status']})"),
        )

    # checkpoint_1: require a valid ToR pool selection before proceeding
    if checkpoint == "checkpoint_1":
        from pipeline.paths import get_run_dir as _get_run_dir

        from api.services.run_artifacts import hydrate_run_artifact

        _run_dir_c1 = _get_run_dir(session_id)
        hydrate_run_artifact(session_id, _run_dir_c1, "tor_data.json")
        tor_path = _run_dir_c1 / "tor_data.json"
        if not tor_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="tor_data.json missing. Wait for checkpoint_1 artifacts before approval.",
            )
        try:
            tor_raw = load_tor_envelope(tor_path, context="api.sessions.approve_checkpoint")
            resolve_selected_tor_pool(
                tor_raw,
                context="api.sessions.approve_checkpoint",
                allow_legacy_data=False,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Mark checkpoint as approved in the manifest
    from pipeline.manifest import update_step as manifest_update_step
    from pipeline.paths import get_run_dir

    run_dir = get_run_dir(session_id)
    if run_dir.exists() and (run_dir / "manifest.json").exists():
        manifest_update_step(run_dir, checkpoint, "approved")

    # Stamp artifact files as approved (audit trail; failures are non-fatal)
    from pipeline.artifacts import stamp_approved

    if checkpoint == "checkpoint_1":
        stamp_approved(run_dir / "cv_data.json")
        stamp_approved(run_dir / "tor_data.json")
    elif checkpoint == "checkpoint_2":
        stamp_approved(run_dir / "mapped_cv.json")
    elif checkpoint == "checkpoint_3":
        stamp_approved(run_dir / "generated_fields.json")

    # Schedule the next phase
    resume_from = CHECKPOINT_RESUME_MAP[checkpoint]

    if resume_from == "cv_tor_mapper":
        from pipeline.orchestrator import run_phase2

        background_tasks.add_task(run_phase2, session_id=session_id)
    elif resume_from == "fields_generator":
        from pipeline.orchestrator import run_phase3

        background_tasks.add_task(run_phase3, session_id=session_id)
    elif resume_from == "renderer":
        from pipeline.orchestrator import run_phase4

        background_tasks.add_task(run_phase4, session_id=session_id)

    return ApproveResponse(
        session_id=session_id,
        approved_checkpoint=checkpoint,
        next_phase=resume_from,
        status="processing",
        message=f"{checkpoint} approved. Next phase '{resume_from}' starting.",
    )


# ── GET /sessions/{id}/review ─────────────────────────────────────────────────


@router.get("/{session_id}/review", response_model=ReviewResponse)
async def get_review(
    session_id: str,
    current_user: CurrentUser,
) -> ReviewResponse:
    """
    Return the content reviewer's issue report.
    Used by the BlockedResolutionPage when status is reviewer_blocked.
    """
    _require_owned_session(session_id, current_user.user_id)

    from pipeline.paths import get_run_dir

    from api.services.run_artifacts import hydrate_run_artifact

    run_dir = get_run_dir(session_id)
    hydrate_run_artifact(session_id, run_dir, "generated_fields.json")
    gf_path = run_dir / "generated_fields.json"
    if not gf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review data not available yet",
        )

    try:
        gf = json.loads(gf_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not read review data: {exc}",
        ) from exc

    review = gf.get("review") or {}
    return ReviewResponse(
        session_id=session_id,
        high_severity=review.get("high_severity", []),
        low_severity=review.get("low_severity", []),
        passed=review.get("passed", False),
        generation_warnings=gf.get("generation_warnings", []),
    )


# ── POST /sessions/{id}/resolve ───────────────────────────────────────────────


@router.post("/{session_id}/resolve", response_model=ResolveResponse)
async def resolve_review(
    session_id: str,
    payload: ResolveRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
) -> ResolveResponse:
    """
    Resolve a blocked content reviewer and resume the pipeline from the compressor.

    Optionally applies dot-path field overrides to generated_fields.json before
    resuming.  If force_pass=True, marks the reviewer as passed regardless of
    flagged issues.
    """
    row = _require_owned_session(session_id, current_user.user_id)

    if row["status"] != "reviewer_blocked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is not reviewer_blocked (current status: {row['status']})",
        )

    import json as _json

    from api.services.run_artifacts import hydrate_run_artifact, push_run_artifact
    from pipeline.manifest import update_step as manifest_update_step
    from pipeline.paths import get_run_dir

    run_dir = get_run_dir(session_id)
    hydrate_run_artifact(session_id, run_dir, "generated_fields.json")
    gf_path = run_dir / "generated_fields.json"

    if not gf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="generated_fields.json not found",
        )

    # Apply dot-path overrides if provided (same traversal as GET /review current_value).
    if payload.overrides:
        try:
            gf = _json.loads(gf_path.read_text(encoding="utf-8"))
            generated = gf.get("generated") or {}
            if not isinstance(generated, dict):
                raise DotPathError("'generated' must be an object to apply overrides")
            for dot_path, value in payload.overrides.items():
                set_by_dot_path(generated, dot_path, value)
            gf["generated"] = generated
            gf_path.write_text(_json.dumps(gf, indent=2, ensure_ascii=False), encoding="utf-8")
            push_run_artifact(session_id, gf_path)
        except DotPathError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to apply overrides: {exc}",
            ) from exc

    # If force_pass, update review block to mark as passed
    if payload.force_pass:
        try:
            gf = _json.loads(gf_path.read_text(encoding="utf-8"))
            if gf.get("review"):
                gf["review"]["passed"] = True
            gf_path.write_text(_json.dumps(gf, indent=2, ensure_ascii=False), encoding="utf-8")
            push_run_artifact(session_id, gf_path)
            manifest_update_step(run_dir, "content_reviewer", "done")
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to force-pass reviewer: {exc}",
            ) from exc

    # Resume from compressor
    from pipeline.orchestrator import run_phase3_resume

    background_tasks.add_task(run_phase3_resume, session_id=session_id)

    return ResolveResponse(
        session_id=session_id,
        status="processing",
        message="Review resolved. Compressor starting.",
    )


# ── POST /sessions/{id}/field-edit ───────────────────────────────────────────


@router.post("/{session_id}/field-edit", response_model=FieldEditResponse)
async def submit_field_edits(
    session_id: str,
    payload: FieldEditRequest,
    current_user: CurrentUser,
) -> FieldEditResponse:
    """
    Apply targeted natural-language edits to specific fields in
    generated_fields["generated"] after the pipeline has completed.

    Replaces POST /comments for post-completion revisions.  Each edit is
    { field_path, instruction }.  The field_editor agent processes them
    sequentially (one LLM call per edit) so each edit operates on the
    already-patched state.  Paths that cannot be resolved or that the agent
    skips are returned in `skipped` — the pipeline proceeds regardless.

    After all edits are applied the session transitions to checkpoint_3_pending.
    Approve with POST /approve/checkpoint_3 to trigger a re-render.

    Session must be in `completed` OR `checkpoint_3_pending` status.
    The latter allows the user to submit a corrected batch for fields that
    were skipped in a previous POST /field-edit call without waiting for a
    full render cycle.
    """
    row = _require_owned_session(session_id, current_user.user_id)

    _FIELD_EDIT_ALLOWED = {"completed", "checkpoint_3_pending"}
    if row["status"] not in _FIELD_EDIT_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Field edits require session status 'completed' or "
                f"'checkpoint_3_pending' (current: {row['status']})."
            ),
        )

    edits = [
        {
            "field_path": e.field_path,
            "instruction": e.instruction,
            "anchor_text": e.anchor_text,
        }
        for e in payload.edits
    ]

    current_round = int(row.get("round") or 1)
    billing_round = current_round + 1

    from api.services.metering import (
        InsufficientCreditsError,
        debit_revision,
        refund_revision,
    )
    from api.services.metering.http import raise_insufficient_credits

    try:
        debit_revision(
            user_id=current_user.user_id,
            session_id=session_id,
            round_num=billing_round,
        )
    except InsufficientCreditsError as exc:
        raise_insufficient_credits(exc)

    # Increment the round counter so the re-rendered output.docx gets the
    # correct label (round_02_giz.docx, round_03_giz.docx, …).
    new_round = increment_round(session_id)

    # Transition to processing before running the agent.
    set_processing(session_id)

    # Run field_editor synchronously so applied/skipped are available for
    # the HTTP response (FIELD_EDITOR_CONTEXT.md §4).
    from pipeline.orchestrator import run_field_editor_task

    try:
        applied, skipped, kq_source = run_field_editor_task(
            session_id=session_id, edits=edits
        )
    except Exception as exc:
        try:
            refund_revision(
                user_id=current_user.user_id,
                session_id=session_id,
                round_num=billing_round,
            )
        except Exception:
            log.exception(
                "Failed to refund revision credits for session %s round %s",
                session_id,
                billing_round,
            )
        set_failed(session_id, str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Field editor failed: {exc}",
        ) from exc

    return FieldEditResponse(
        session_id=session_id,
        status="checkpoint_3_pending",
        round=new_round,
        applied=applied,
        skipped=skipped,
        kq_source=kq_source,
        message="Field edits applied. Awaiting checkpoint_3 approval before re-render.",
    )


# ── GET /sessions/{id}/output ─────────────────────────────────────────────────


@router.get("/{session_id}/output", response_model=OutputResponse)
async def get_output(
    session_id: str,
    current_user: CurrentUser,
) -> OutputResponse:
    """
    Return the generated CVData payload (GeneratedFieldsPayload in the data flow diagram).
    Used by the FinalOutputPage after checkpoint_3 approval and renderer completion.
    """
    _require_owned_session(session_id, current_user.user_id)

    import json as _json

    from pipeline.paths import get_run_dir

    from api.services.run_artifacts import hydrate_run_artifact

    run_dir = get_run_dir(session_id)
    hydrate_run_artifact(session_id, run_dir, "generated_fields.json")
    gf_path = run_dir / "generated_fields.json"

    if not gf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Output data not available — pipeline has not completed",
        )

    try:
        gf = _json.loads(gf_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not read output data: {exc}",
        ) from exc

    cv_data = gf.get("generated")
    if not cv_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated CV data not found in output",
        )

    return OutputResponse(
        session_id=session_id,
        cv_data=cv_data,
        generation_warnings=gf.get("generation_warnings", []),
        review=gf.get("review"),
        compression=gf.get("compression"),
    )


# ── GET /sessions/{id}/warnings ───────────────────────────────────────────────


@router.get("/{session_id}/warnings", response_model=WarningsResponse)
async def get_warnings(
    session_id: str,
    current_user: CurrentUser,
) -> WarningsResponse:
    """
    Return all pipeline warnings aggregated from every stage for this session.

    Four sources are collected and tagged by stage:
      - cv_data.json        → extraction_warnings[]   (Agent 1 extraction issues)
      - mapped_cv.json      → alignment.warnings[]    (Agent 3 scoring issues)
      - manifest.json       → warnings[]              (orchestrator-level warnings)
      - generated_fields.json → generation_warnings[] (Agent 4/6 generation issues)

    R7-M: these warning lists were previously written to disk but never
    transmitted to the frontend. This endpoint is additive — no existing
    response shapes are modified.
    """
    _require_owned_session(session_id, current_user.user_id)

    from api.services.run_artifacts import hydrate_run_artifact
    from pipeline.paths import get_run_dir

    run_dir = get_run_dir(session_id)
    hydrate_run_artifact(session_id, run_dir, "generated_fields.json")
    warnings: list[WarningEntry] = []

    # Stage 1: extraction warnings from cv_data.json
    cv_data_path = run_dir / "cv_data.json"
    if cv_data_path.exists():
        try:
            cv_raw = json.loads(cv_data_path.read_text(encoding="utf-8"))
            for msg in cv_raw.get("data", {}).get("extraction_warnings", []):
                warnings.append(
                    WarningEntry(stage="extraction", kind="extraction_warning", message=str(msg))
                )
        except Exception:
            pass  # non-fatal — return what we can

    # Stage 2: alignment warnings from mapped_cv.json
    mapped_path = run_dir / "mapped_cv.json"
    if mapped_path.exists():
        try:
            mapped_raw = json.loads(mapped_path.read_text(encoding="utf-8"))
            for msg in mapped_raw.get("alignment", {}).get("warnings", []):
                warnings.append(
                    WarningEntry(stage="alignment", kind="alignment_warning", message=str(msg))
                )
        except Exception:
            pass

    # Stage 3: manifest-level warnings from manifest.json
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            for w in manifest_raw.get("warnings", []):
                if isinstance(w, dict):
                    warnings.append(
                        WarningEntry(
                            stage="manifest",
                            kind=w.get("kind", "manifest_warning"),
                            message=w.get("message", str(w)),
                            details=w.get("details"),
                        )
                    )
                else:
                    warnings.append(
                        WarningEntry(stage="manifest", kind="manifest_warning", message=str(w))
                    )
        except Exception:
            pass

    # Stage 4: generation warnings from generated_fields.json
    gf_path = run_dir / "generated_fields.json"
    if gf_path.exists():
        try:
            gf_raw = json.loads(gf_path.read_text(encoding="utf-8"))
            for msg in gf_raw.get("generation_warnings", []):
                warnings.append(
                    WarningEntry(stage="generation", kind="generation_warning", message=str(msg))
                )
        except Exception:
            pass

    # Build per-stage counts
    counts: dict[str, int] = {"extraction": 0, "alignment": 0, "manifest": 0, "generation": 0}
    for w in warnings:
        if w.stage in counts:
            counts[w.stage] += 1

    return WarningsResponse(session_id=session_id, warnings=warnings, counts=counts)
