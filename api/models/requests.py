from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Full pipeline state machine — coarse DB status values.
# checkpoint_N_pending: pipeline halted, waiting for human approval.
# reviewer_blocked:     Agent 5 flagged high-severity issues needing resolution.
SessionStatus = Literal[
    "queued",
    "processing",
    "checkpoint_1_pending",
    "checkpoint_2_pending",
    "reviewer_blocked",
    "checkpoint_3_pending",
    "completed",
    "failed",
]

# Active statuses used for rate-limit counting.
ACTIVE_STATUSES: tuple[str, ...] = (
    "queued",
    "processing",
    "checkpoint_1_pending",
    "checkpoint_2_pending",
    "reviewer_blocked",
    "checkpoint_3_pending",
)

TargetFormat = Literal["giz", "world_bank"]

# Map from checkpoint name (as used in the manifest) to the DB status value.
CHECKPOINT_STATUS_MAP: dict[str, str] = {
    "checkpoint_1": "checkpoint_1_pending",
    "checkpoint_2": "checkpoint_2_pending",
    "checkpoint_3": "checkpoint_3_pending",
}

# Map from approved checkpoint to the next phase's resume-from key.
CHECKPOINT_RESUME_MAP: dict[str, str] = {
    "checkpoint_1": "cv_tor_mapper",
    "checkpoint_2": "fields_generator",
    "checkpoint_3": "renderer",
}


# ── Session creation ──────────────────────────────────────────────────────────


class SessionCreateRequest(BaseModel):
    target_format: TargetFormat
    source_filename: str = Field(min_length=1)
    tor_filename: str | None = None
    # Pipeline identity params — written to the session row and passed to agents
    proposed_position: str | None = Field(default=None, description="Proposed position title")
    category: str | None = Field(default=None, description="Expert category (e.g. Senior Expert)")
    employer: str | None = Field(default=None, description="Employer / consulting firm name")
    years_with_firm: str | None = Field(default=None, description="Years with the firm")
    # Optional pipeline parameters stored on the session row
    page_limit: int | None = Field(default=None, ge=1, le=100)
    job_description: str | None = None
    recruiter_comments: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    status: SessionStatus


# ── Session status ────────────────────────────────────────────────────────────


class SessionStatusResponse(BaseModel):
    session_id: str
    user_id: str | None = None
    status: SessionStatus
    target_format: TargetFormat
    round: int = 1
    source_filename: str
    tor_filename: str | None = None
    source_storage_key: str | None = None
    tor_storage_key: str | None = None
    output_storage_key: str | None = None
    output_file_path: str | None = None
    # Only populated on relevant statuses — callers should check status first
    download_url: str | None = None  # fresh signed URL, only when completed
    error_message: str | None = None  # only when failed
    page_limit: int | None = None
    job_description: str | None = None
    recruiter_comments: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionStatusUpdateRequest(BaseModel):
    status: SessionStatus
    output_file_path: str | None = None
    error_message: str | None = None


# ── File upload ───────────────────────────────────────────────────────────────


class FileUploadResponse(BaseModel):
    storage_key: str
    signed_url: str
    expires_in: int


class SignedDownloadResponse(BaseModel):
    signed_url: str
    expires_in: int


# ── Session start ─────────────────────────────────────────────────────────────


class SessionStartResponse(BaseModel):
    session_id: str
    status: SessionStatus
    message: str


# ── Revision comments ─────────────────────────────────────────────────────────


class CommentsRequest(BaseModel):
    comment: str = Field(min_length=1, description="Recruiter feedback for the revision run")


class CommentsResponse(BaseModel):
    session_id: str
    status: SessionStatus
    round: int
    message: str


# ── Checkpoint approval ───────────────────────────────────────────────────────


class ApproveRequest(BaseModel):
    notes: str = Field(default="", description="Optional human notes recorded with the approval")


class ApproveResponse(BaseModel):
    session_id: str
    approved_checkpoint: str
    next_phase: str
    status: SessionStatus
    message: str


# ── Reviewer resolve ──────────────────────────────────────────────────────────


class ResolveRequest(BaseModel):
    overrides: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Dot-path field patches applied before resuming the pipeline. "
            "E.g. {'generated_fields.0.content': 'Revised bullet text'}."
        ),
    )
    force_pass: bool = Field(
        default=False,
        description="If true, mark the reviewer as passed regardless of high-severity issues.",
    )


class ResolveResponse(BaseModel):
    session_id: str
    status: SessionStatus
    message: str


# ── Manifest polling ──────────────────────────────────────────────────────────


class ManifestStepResponse(BaseModel):
    name: str
    status: str
    completed_at: str | None = None


class ManifestResponse(BaseModel):
    session_id: str
    db_status: SessionStatus
    steps: list[ManifestStepResponse]
    checkpoint_pending: str | None = None  # e.g. "checkpoint_1" if pending
    reviewer_blocked: bool = False


# ── Pipeline output data ──────────────────────────────────────────────────────


class MappedCVResponse(BaseModel):
    session_id: str
    cv_data: dict[str, Any]
    alignment: dict[str, Any]


class ReviewResponse(BaseModel):
    session_id: str
    high_severity: list[dict[str, Any]]
    low_severity: list[dict[str, Any]]
    passed: bool
    generation_warnings: list[str]


class OutputResponse(BaseModel):
    session_id: str
    cv_data: dict[str, Any]
    generation_warnings: list[str]
    review: dict[str, Any] | None
    compression: dict[str, Any] | None
