"""Session lifecycle endpoints backed by Supabase."""

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from api.models.requests import (
    CHECKPOINT_RESUME_MAP,
    CHECKPOINT_STATUS_MAP,
    ApproveRequest,
    ApproveResponse,
    CommentsRequest,
    CommentsResponse,
    FileUploadResponse,
    ManifestResponse,
    ManifestStepResponse,
    OutputResponse,
    ResolveRequest,
    ResolveResponse,
    ReviewResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionStartResponse,
    SessionStatusResponse,
    SessionStatusUpdateRequest,
    SignedDownloadResponse,
)
from api.services import storage as storage_service
from api.services.auth import AuthenticatedUser, get_current_user
from api.services.database import (
    count_active_sessions,
    create_session_row,
    get_session_row,
    update_session_row,
    update_session_storage_keys,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]

# File types accepted for source CV uploads.
_ALLOWED_EXTENSIONS = {".docx", ".pdf"}
# Maximum concurrent active sessions per user (queued + processing).
_MAX_ACTIVE_SESSIONS = 3


# ── Helpers ───────────────────────────────────────────────────────────────────


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


# ── POST /sessions ────────────────────────────────────────────────────────────


@router.post("", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreateRequest,
    current_user: CurrentUser,
) -> SessionCreateResponse:
    # World Bank format not yet supported — renderer not implemented.
    if payload.target_format == "world_bank":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "World Bank format is not yet available. " "Only 'giz' is supported at this time."
            ),
        )

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
            proposed_position=payload.proposed_position,
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


# ── POST /sessions/{id}/comments ──────────────────────────────────────────────


@router.post("/{session_id}/comments", response_model=CommentsResponse)
async def submit_revision_comment(
    session_id: str,
    payload: CommentsRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
) -> CommentsResponse:
    """
    Submit recruiter feedback and trigger a revision run.

    Only allowed when the session status is 'completed'.  The new comment is
    appended to the existing recruiter_comments field with a round prefix so
    the full feedback history is preserved.  The background task then calls
    run_revision() with the updated comments string.
    """
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
        message="Revision queued. Poll /status for updates.",
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

    run_dir = get_run_dir(session_id)
    if not run_dir.exists() or not (run_dir / "manifest.json").exists():
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

    # Mark checkpoint as approved in the manifest
    from pipeline.manifest import update_step as manifest_update_step
    from pipeline.paths import get_run_dir

    run_dir = get_run_dir(session_id)
    if run_dir.exists() and (run_dir / "manifest.json").exists():
        manifest_update_step(run_dir, checkpoint, "approved")

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

    run_dir = get_run_dir(session_id)
    gf_path = run_dir / "generated_fields.json"
    if not gf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review data not available yet",
        )

    try:
        gf = __import__("json").loads(gf_path.read_text(encoding="utf-8"))
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

    from pipeline.manifest import update_step as manifest_update_step
    from pipeline.paths import get_run_dir

    run_dir = get_run_dir(session_id)
    gf_path = run_dir / "generated_fields.json"

    if not gf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="generated_fields.json not found",
        )

    # Apply dot-path overrides if provided
    if payload.overrides:
        try:
            gf = _json.loads(gf_path.read_text(encoding="utf-8"))
            generated = gf.get("generated", {})
            for dot_path, value in payload.overrides.items():
                parts = dot_path.split(".")
                obj = generated
                for part in parts[:-1]:
                    obj = obj[int(part)] if part.isdigit() else obj[part]
                last = parts[-1]
                if last.isdigit():
                    obj[int(last)] = value
                else:
                    obj[last] = value
            gf["generated"] = generated
            gf_path.write_text(_json.dumps(gf, indent=2, ensure_ascii=False), encoding="utf-8")
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

    run_dir = get_run_dir(session_id)
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
