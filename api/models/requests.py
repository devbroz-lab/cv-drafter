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
    "field_editor_pending",
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
    "field_editor_pending",
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
    # proposed_position is NOT set at session creation; it is derived from the selected
    # ToR pool's position_title at checkpoint_1 (POST /tor/select-pool).
    category: str | None = Field(default=None, description="Expert category (e.g. Senior Expert)")
    employer: str | None = Field(default=None, description="Employer / consulting firm name")
    years_with_firm: str | None = Field(default=None, description="Years with the firm")
    # Optional pipeline parameters stored on the session row
    page_limit: int | None = Field(default=None, ge=1, le=100)
    job_description: str | None = None
    recruiter_comments: str | None = None
    # Compression overrides — stored in manifest.params (not in DB).
    # When omitted, FORMAT_PROFILES[donor] defaults are used.
    target_words: int | None = Field(
        default=None, ge=0, description="Hard word-count cap for compressor (0 = use ratio)"
    )
    compression_ratio: float | None = Field(
        default=None, gt=0, le=1, description="Compressor fallback ratio when target_words is 0"
    )


class SessionCreateResponse(BaseModel):
    session_id: str
    status: SessionStatus


# ── Session status ────────────────────────────────────────────────────────────


class SessionSummary(BaseModel):
    """Lightweight session row for GET /sessions list."""

    session_id: str
    status: SessionStatus
    target_format: TargetFormat
    round: int = 1
    source_filename: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


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
    started_at: str | None = None  # ISO-8601, stamped when the step first runs
    completed_at: str | None = None


class ManifestResponse(BaseModel):
    session_id: str
    db_status: SessionStatus
    steps: list[ManifestStepResponse]
    checkpoint_pending: str | None = None  # e.g. "checkpoint_1" if pending
    reviewer_blocked: bool = False
    # Real-time progress signals for the polling UI (additive).
    progress: int = 0  # 0–100 derived from step statuses
    current_step: str | None = None  # name of the step currently in flight
    # Agent warnings accumulated so far, streamed each poll (stage = step name).
    # Forward-ref string + model_rebuild() at end of module (WarningEntry is
    # defined later in this file).
    warnings: list["WarningEntry"] = Field(default_factory=list)


# ── ToR pool selection ────────────────────────────────────────────────────────


class TorPoolSelectionRequest(BaseModel):
    selected_pool_index: int = Field(ge=0, description="Index into tor_data.pools")


class TorPoolSelectionResponse(BaseModel):
    session_id: str
    selected_pool_index: int
    pool_count: int
    position_title: str | None = None
    message: str


class TorPoolsResponse(BaseModel):
    session_id: str
    pools: list[dict[str, Any]]
    selected_pool_index: int | None = None


# ── Field editor ──────────────────────────────────────────────────────────────


class FieldEditItem(BaseModel):
    field_path: str = Field(
        min_length=1, description="Dot-path relative to generated_fields['generated']"
    )
    instruction: str = Field(
        min_length=1, description="Natural language instruction for the edit agent"
    )
    anchor_text: str | None = Field(
        default=None,
        description=(
            "Optional clicked paragraph/cell text from the Docx viewer. "
            "Used to resolve placeholder paths like paragraph_<n> to key_qualifications[i]."
        ),
    )


class FieldEditRequest(BaseModel):
    edits: list[FieldEditItem] = Field(
        min_length=1,
        max_length=5,
        description="1–5 targeted field edits to apply before compression",
    )


class FieldEditApplied(BaseModel):
    """A single edit that was written to generated_fields."""

    path: str = Field(description="Dot-path field that was updated")
    instruction: str = Field(description="Recruiter instruction echoed from the request")
    previous_value: str = Field(
        description="Value before the edit (truncated for display)",
        max_length=201,
    )
    new_value: str = Field(
        description="Value after the edit (truncated for display)",
        max_length=201,
    )


class FieldEditSkip(BaseModel):
    """A single edit that was not applied, with the reason it was skipped.

    Reasons are capped at 200 characters (with a trailing ellipsis when
    truncated) so frontends can display them inline without wrapping concerns.

    Reason categories:
      - "path resolution failed: ..."  — the field_path could not be traversed
      - "resolved value is <type>, not a scalar. ..."  — path points to a list/dict
      - "API or parse error: ..."  — Claude call failed or returned bad JSON
      - "<LLM-supplied sentence>"  — agent chose to skip (action = "skip")
      - "write-back failed: ..."  — value resolved and edited but could not be written
    """

    path: str = Field(description="The field_path that was not applied")
    reason: str = Field(
        description=(
            "Human-readable explanation, max 200 chars. "
            "Truncated with \u2026 if the source was longer."
        ),
        max_length=201,  # 200 chars + 1 for the ellipsis character
    )


class FieldEditResponse(BaseModel):
    session_id: str
    status: SessionStatus
    round: int
    applied: list[FieldEditApplied]
    skipped: list[FieldEditSkip]  # was list[str] — see BREAKING CHANGE note in API.md
    message: str
    kq_source: Literal["ai_generated", "extracted", "absent"] = Field(
        description=(
            "Which data source provided the key_qualifications bullets that "
            "field-edits targeted, computed from the post-edit state of "
            "generated_fields.json. "
            "'ai_generated' = Agent 4's ToR-tailored content (generated_fields[j].content paths); "
            "'extracted' = Agent 1's raw CV extraction — Agent 4 produced no usable content "
            "(key_qualifications[i] paths); "
            "'absent' = no bullets in either source."
        ),
    )


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


# ── Pipeline warnings aggregation ────────────────────────────────────────────


class WarningEntry(BaseModel):
    """A single warning from any stage of the pipeline."""

    stage: str = Field(
        description=(
            "Pipeline stage that produced the warning. One of: "
            "'extraction' (Agent 1), 'alignment' (Agent 3), "
            "'manifest' (orchestrator), 'generation' (Agent 4/6)."
        )
    )
    kind: str = Field(
        description=(
            "Warning kind/type as written by the pipeline stage. "
            "Examples: 'threshold_activation', 'input_field_truncated', "
            "'generation_warnings_high', 'date_inversion'."
        )
    )
    message: str = Field(description="Human-readable warning message.")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured detail dict for programmatic consumers.",
    )


class WarningsResponse(BaseModel):
    """Aggregated warnings from all pipeline stages for a session."""

    session_id: str
    warnings: list[WarningEntry] = Field(
        description=(
            "All warnings across extraction, alignment, manifest, and generation stages, "
            "in pipeline stage order. Empty list when no warnings were produced."
        )
    )
    counts: dict[str, int] = Field(
        description="Count of warnings per stage (keys: extraction, alignment, manifest, generation).",
    )


# Resolve the forward reference in ManifestResponse.warnings now that
# WarningEntry is defined above.
ManifestResponse.model_rebuild()
