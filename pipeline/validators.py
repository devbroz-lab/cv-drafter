"""
Pipeline output validators — hard-block checks and soft-flag checks between
agent stages.

Hard-block validators raise ``PipelineValidationError`` and halt the pipeline.
Soft-flag check functions return a list of warning dicts (empty list = clean);
callers write them to the manifest via ``manifest.append_warning``.

Validators operate on the artifact files directly (same JSON the agents
write) rather than intercepting LLM responses, so they are agent-agnostic
and can also be run offline as a diagnostic script against any session's
run directory.

Public API (hard-block)
-----------------------
PipelineValidationError
    Raised by hard-block validators.  Carries stage, message, details.

validate_fields_generator_output(run_dir: Path) -> None
    Hard block after Agent 4: raises if every generated_fields entry has
    empty content.

Public API (soft-flag checks)
------------------------------
check_fields_generator_warnings(run_dir: Path) -> list[dict]
    Returns warning entries if generation_warnings count is high or
    any generated_fields entry has empty content (partial, not total).

check_content_reviewer_warnings(run_dir: Path) -> list[dict]
    Returns warning entries if the review block is null or high_severity
    count is unusually high.

check_compressor_warnings(run_dir: Path) -> list[dict]
    Returns warning entries if compression block is null, applied=false,
    target_not_reached=true, or words_after is suspiciously low.
"""

from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared exception
# ---------------------------------------------------------------------------


class PipelineValidationError(Exception):
    """
    Raised when an agent's output fails a hard-block validator.

    Attributes
    ----------
    stage : str
        The pipeline stage (manifest step name) where the failure was detected.
    message : str
        Human-readable explanation, suitable for set_failed() and log output.
    details : dict
        Structured diagnostic payload (counts, donor, field keys, etc.)
        included in the error message string.
    """

    def __init__(self, stage: str, message: str, details: dict | None = None):
        self.stage = stage
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def __str__(self) -> str:
        if self.details:
            detail_str = ", ".join(f"{k}={v!r}" for k, v in self.details.items())
            return f"[{self.stage}] {self.message} ({detail_str})"
        return f"[{self.stage}] {self.message}"


# ---------------------------------------------------------------------------
# Validator: Agent 4 — Fields Generator
# ---------------------------------------------------------------------------


def validate_fields_generator_output(run_dir: Path) -> None:
    """
    Hard-block validator: raises PipelineValidationError if every entry in
    ``generated_fields.json["generated"]["generated_fields"]`` has empty
    content (all-or-nothing rule).

    The check uses the same all-or-nothing rule described in the diagnostic
    doc — a hard block fires only when EVERY generative entry is empty,
    matching the observed failure mode where Agent 4 returns the correct
    skeleton but leaves all content fields as empty strings.

    Parameters
    ----------
    run_dir : Path
        Session run directory (runs/{session_id}/).

    Raises
    ------
    PipelineValidationError
        If generated_fields.json is missing, cannot be parsed, or every
        generated_fields[i].content is empty / whitespace-only.
    """
    gf_path = run_dir / "generated_fields.json"

    if not gf_path.exists():
        raise PipelineValidationError(
            stage="fields_generator",
            message=(
                "generated_fields.json not found after Agent 4 — "
                "cannot validate output."
            ),
        )

    try:
        gf = json.loads(gf_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PipelineValidationError(
            stage="fields_generator",
            message=f"generated_fields.json could not be parsed: {exc}",
        ) from exc

    generated = gf.get("generated", {})
    entries: list = generated.get("generated_fields", [])

    # Determine donor and generative_field_keys for the error message.
    # These come from manifest.json params; best-effort only — validation
    # fires regardless of whether the manifest can be read.
    donor = "unknown"
    generative_field_keys: list[str] = []
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        params = manifest.get("params", {})
        donor = params.get("donor", "unknown")

        from models import FORMAT_PROFILES  # local import to avoid circular deps
        profile = FORMAT_PROFILES.get(donor)
        if profile:
            generative_field_keys = list(profile.generative_field_keys)
    except Exception:
        pass  # manifest read is best-effort

    total = len(entries)
    non_empty = sum(
        1 for e in entries
        if isinstance(e, dict) and str(e.get("content", "")).strip()
    )
    empty = total - non_empty

    # Hard block: all-or-nothing — fires only when EVERY entry is empty.
    if total == 0 or non_empty == 0:
        raise PipelineValidationError(
            stage="fields_generator",
            message=(
                "Agent 4 produced empty content for all generated_fields entries "
                f"(donor={donor!r}, generative_field_keys={generative_field_keys}) "
                "— pipeline halted before Agent 5. "
                "This indicates a generation failure; inspect the model output."
            ),
            details={
                "donor": donor,
                "generative_field_keys": generative_field_keys,
                "total_entries": total,
                "empty_entries": empty,
                "non_empty_entries": non_empty,
            },
        )


# ---------------------------------------------------------------------------
# Fix 5b — Soft-flag check functions (Round 5)
# ---------------------------------------------------------------------------

# Threshold: more than this many generation_warnings is flagged as a soft concern.
_GENERATION_WARNINGS_HIGH_THRESHOLD: int = 3

# Threshold: words_after below this value after compression is suspicious.
_COMPRESSOR_MIN_WORDS_AFTER: int = 200


def check_fields_generator_warnings(run_dir: Path) -> list[dict]:
    """
    Soft-flag check after Agent 4.

    Returns warning entries (not exceptions) for:
    - generation_warnings count exceeds ``_GENERATION_WARNINGS_HIGH_THRESHOLD``
    - Any (but not all) ``generated_fields[].content`` is empty (partial failure).
      The hard-block in ``validate_fields_generator_output`` handles the all-empty case.

    Returns an empty list when everything looks healthy.
    """
    gf_path = run_dir / "generated_fields.json"
    if not gf_path.exists():
        return []
    try:
        gf = json.loads(gf_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    warnings: list[dict] = []
    generated = gf.get("generated", {})
    gen_warnings: list = gf.get("generation_warnings", []) or []

    if len(gen_warnings) > _GENERATION_WARNINGS_HIGH_THRESHOLD:
        warnings.append({
            "stage": "fields_generator",
            "kind": "generation_warnings_high",
            "message": (
                f"Agent 4 emitted {len(gen_warnings)} generation_warnings "
                f"(threshold: {_GENERATION_WARNINGS_HIGH_THRESHOLD}). "
                "Review for low-confidence bullets or alignment gaps."
            ),
            "details": {
                "count": len(gen_warnings),
                "threshold": _GENERATION_WARNINGS_HIGH_THRESHOLD,
                "warnings": gen_warnings,
            },
        })

    entries: list = generated.get("generated_fields", [])
    empty_count = sum(
        1 for e in entries
        if isinstance(e, dict) and not str(e.get("content", "")).strip()
    )
    if 0 < empty_count < len(entries):  # partial — all-empty is handled by hard-block
        warnings.append({
            "stage": "fields_generator",
            "kind": "partial_empty_generated_fields",
            "message": (
                f"Agent 4 produced {empty_count} of {len(entries)} "
                "generated_fields entries with empty content. "
                "The document may have gaps for those fields."
            ),
            "details": {
                "total_entries": len(entries),
                "empty_entries": empty_count,
            },
        })

    return warnings


def check_content_reviewer_warnings(run_dir: Path) -> list[dict]:
    """
    Soft-flag check after Agent 5.

    Returns warning entries for:
    - review block is null (reviewer did not run or failed silently).
    - high_severity count exceeds 5 (unusually high; may indicate systemic issue).

    Returns an empty list when everything looks healthy.
    """
    gf_path = run_dir / "generated_fields.json"
    if not gf_path.exists():
        return []
    try:
        gf = json.loads(gf_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    warnings: list[dict] = []
    review = gf.get("review")

    if review is None:
        warnings.append({
            "stage": "content_reviewer",
            "kind": "review_block_null",
            "message": (
                "Content reviewer did not write a review block. "
                "The review step may have failed silently."
            ),
            "details": {},
        })
        return warnings  # can't check high_severity if no review block

    high_sev: list = review.get("high_severity", []) or []
    if len(high_sev) > 5:
        warnings.append({
            "stage": "content_reviewer",
            "kind": "high_severity_count_unusual",
            "message": (
                f"Content reviewer flagged {len(high_sev)} high-severity issues "
                "(threshold: 5). This may indicate systemic input quality problems."
            ),
            "details": {
                "count": len(high_sev),
                "threshold": 5,
            },
        })

    return warnings


def check_compressor_warnings(run_dir: Path) -> list[dict]:
    """
    Soft-flag check after Agent 6.

    Returns warning entries for:
    - compression block is null (compressor did not run or failed silently).
    - applied=false (compressor skipped — content already within target).
    - target_not_reached=true (compressor could not reach target).
    - words_after below ``_COMPRESSOR_MIN_WORDS_AFTER`` (suspicious over-compression).

    Returns an empty list when everything looks healthy.
    """
    gf_path = run_dir / "generated_fields.json"
    if not gf_path.exists():
        return []
    try:
        gf = json.loads(gf_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    warnings: list[dict] = []
    compression = gf.get("compression")

    if compression is None:
        warnings.append({
            "stage": "compressor",
            "kind": "compression_block_null",
            "message": (
                "Compressor did not write a compression block. "
                "The compression step may have failed silently."
            ),
            "details": {},
        })
        return warnings

    if not compression.get("applied", True):
        warnings.append({
            "stage": "compressor",
            "kind": "applied_false",
            "message": (
                "Compressor skipped — content was already within the target "
                "word count. No compression was applied."
            ),
            "details": {
                "words_before": compression.get("words_before"),
                "target_words": compression.get("target_words"),
            },
        })

    if compression.get("target_not_reached"):
        warnings.append({
            "stage": "compressor",
            "kind": "target_not_reached",
            "message": (
                "Compressor could not reach the target word count without "
                "violating compression rules. Manual review may be needed."
            ),
            "details": {
                "words_after": compression.get("words_after"),
                "target_words": compression.get("target_words"),
            },
        })

    words_after = compression.get("words_after", 0) or 0
    if compression.get("applied") and words_after < _COMPRESSOR_MIN_WORDS_AFTER:
        warnings.append({
            "stage": "compressor",
            "kind": "words_after_suspiciously_low",
            "message": (
                f"Compressor output has only {words_after} words — below the "
                f"minimum threshold of {_COMPRESSOR_MIN_WORDS_AFTER}. "
                "The document may be too sparse for submission."
            ),
            "details": {
                "words_after": words_after,
                "min_threshold": _COMPRESSOR_MIN_WORDS_AFTER,
            },
        })

    return warnings


# ---------------------------------------------------------------------------
# Fix Y — Soft-flag check function (Round 6)
# ---------------------------------------------------------------------------


def check_tor_summarizer_warnings(run_dir: Path) -> list[dict]:
    """
    Soft-flag check after Agent 2.

    Reads tor_data.json. For each pool in pools[]:
    - If all three scoring_keywords lists are empty AND the pool has non-empty
      content (position_title or key_tasks), emit kind 'scoring_keywords_empty'.
    - If position_title is empty AND the ToR has any content, emit kind
      'position_title_empty'.

    Returns [] when the file is missing, pools is empty (no-ToR run), or
    all checks pass.
    """
    tor_path = run_dir / "tor_data.json"
    if not tor_path.exists():
        return []
    try:
        tor = json.loads(tor_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    pools: list = tor.get("pools", []) or []
    if not pools:
        return []

    warnings: list[dict] = []
    for i, pool in enumerate(pools):
        has_content = bool(
            str(pool.get("position_title", "")).strip()
            or pool.get("key_tasks", [])
        )

        # Check position_title empty when there is other pool content
        if not str(pool.get("position_title", "")).strip() and has_content:
            warnings.append({
                "stage": "tor_summarizer",
                "kind": "position_title_empty",
                "message": (
                    f"Pool[{i}] position_title is empty despite non-empty ToR content. "
                    "Agent 2 may have failed to extract the role title."
                ),
                "details": {"pool_index": i},
            })

        # Check all three scoring_keywords lists empty
        scoring = pool.get("scoring_keywords", {}) or {}
        explicit = scoring.get("explicit", []) or []
        scope_implied = scoring.get("scope_implied", []) or []
        role_implied = scoring.get("role_implied", []) or []
        all_empty = not explicit and not scope_implied and not role_implied

        if all_empty and has_content:
            warnings.append({
                "stage": "tor_summarizer",
                "kind": "scoring_keywords_empty",
                "message": (
                    f"Pool[{i}] all three scoring_keywords lists are empty "
                    "(explicit, scope_implied, role_implied). "
                    "Relevance scoring will be degraded for this pool."
                ),
                "details": {"pool_index": i, "position_title": pool.get("position_title", "")},
            })

    return warnings
