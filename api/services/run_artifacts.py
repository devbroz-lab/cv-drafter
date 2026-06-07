"""
Persist selected run-dir JSON artifacts to Supabase Storage.

Railway (and other multi-instance hosts) use ephemeral local disk under
``runs/{session_id}/``. Uploading manifest/tor_data after each write lets
any replica hydrate files before API handlers read them.
"""

from __future__ import annotations

import logging
from pathlib import Path

from api.services.storage import download_bytes, upload_bytes

log = logging.getLogger(__name__)

# Run-dir JSON the API reads after deploy / across replicas.
_SYNCED_ARTIFACTS = frozenset({"manifest.json", "tor_data.json", "generated_fields.json"})


def artifact_storage_key(session_id: str, filename: str) -> str:
    return f"{session_id}/artifacts/{filename}"


def push_run_artifact(session_id: str, local_path: Path) -> None:
    """Upload a run artifact if it exists locally. Failures are logged only."""
    if local_path.name not in _SYNCED_ARTIFACTS:
        return
    if not local_path.is_file():
        return
    try:
        upload_bytes(
            object_path=artifact_storage_key(session_id, local_path.name),
            data=local_path.read_bytes(),
            content_type="application/json",
        )
    except Exception:
        log.warning(
            "Could not upload run artifact %s for session %s",
            local_path.name,
            session_id,
            exc_info=True,
        )


def hydrate_run_artifact(session_id: str, run_dir: Path, filename: str) -> bool:
    """
    Ensure ``run_dir/filename`` exists locally, downloading from Storage if needed.
    Returns True when the file is present after this call.
    """
    if filename not in _SYNCED_ARTIFACTS:
        return False
    local_path = run_dir / filename
    if local_path.is_file():
        return True
    try:
        data = download_bytes(artifact_storage_key(session_id, filename))
        run_dir.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        log.info("Hydrated %s for session %s from Storage", filename, session_id)
        return True
    except Exception:
        log.debug(
            "No stored artifact %s for session %s (or download failed)",
            filename,
            session_id,
            exc_info=True,
        )
        return False
