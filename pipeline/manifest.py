"""
Per-run manifest — step-level progress tracking written to runs/{session_id}/manifest.json.

The manifest is the fine-grained source of truth for pipeline progress.
The Supabase DB session row holds the coarse status (processing, checkpoint_1_pending, etc.).
Both are updated in tandem by the orchestrator.

STEP_ORDER defines the canonical execution sequence.  Each step has a status:
  waiting   — not yet started
  running   — currently executing
  done      — completed successfully
  failed    — raised an exception
  blocked   — content_reviewer flagged high-severity issues (human must resolve)
  pending   — checkpoint reached, waiting for human approval
  approved  — checkpoint approved by human (pipeline resumes next phase)
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

STEP_ORDER: list[str] = [
    "cv_extractor",
    "tor_summarizer",
    "checkpoint_1",
    "cv_tor_mapper",
    "checkpoint_2",
    "fields_generator",
    "content_reviewer",
    "compressor",
    "checkpoint_3",
    "renderer",
]

_TERMINAL_STATUSES = {"done", "failed", "blocked", "approved"}


def generate_run_id() -> str:
    """Generate a timestamped run ID: YYYYMMDD_HHMMSS_xxxx."""
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:4]
    return f"{ts}_{short}"


def create_manifest(
    run_dir: Path,
    run_id: str,
    cv_path: str,
    tor_path: str,
    params: dict,
) -> None:
    """Write a fresh manifest.json into *run_dir*."""
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "cv_path": cv_path,
        "tor_path": tor_path,
        "params": params,
        "steps": [{"name": s, "status": "waiting", "completed_at": None} for s in STEP_ORDER],
    }
    _write(run_dir, manifest)


def load_manifest(run_dir: Path) -> dict:
    """Read and parse manifest.json from *run_dir*."""
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


def update_step(run_dir: Path, step_name: str, status: str) -> None:
    """Set *step_name* status in the manifest, recording a timestamp for terminal statuses."""
    manifest = load_manifest(run_dir)
    for step in manifest["steps"]:
        if step["name"] == step_name:
            step["status"] = status
            if status in _TERMINAL_STATUSES:
                step["completed_at"] = datetime.now(UTC).isoformat()
            break
    _write(run_dir, manifest)


def get_step_status(run_dir: Path, step_name: str) -> str:
    """Return the current status string for *step_name*, or 'waiting' if not found."""
    manifest = load_manifest(run_dir)
    for step in manifest["steps"]:
        if step["name"] == step_name:
            return step["status"]
    return "waiting"


def _write(run_dir: Path, manifest: dict) -> None:
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
