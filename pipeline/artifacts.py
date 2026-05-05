"""
Artifact file helpers for the pipeline.

Provides stamp_approved() to mark an artifact wrapper as approved
after a human checkpoint approval.  This is an audit trail only
-- the DB sessions.status column is the authoritative control signal;
the orchestrator never reads artifact approved/approved_at fields to
make pipeline decisions.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pipeline.text_encoding import UTF_8

log = logging.getLogger(__name__)


def stamp_approved(path: Path) -> None:
    """
    Set approved=True and approved_at=<utc-iso> on an artifact wrapper file.

    Called by the approval HTTP handler after each checkpoint is approved.
    Failures are logged but not raised -- a disk error after the DB update
    has already succeeded must not block the pipeline (Decision 1B).

    Args:
        path: Absolute path to the artifact JSON file
              (cv_data.json, tor_data.json, mapped_cv.json,
              or generated_fields.json).
    """
    try:
        raw = json.loads(path.read_text(encoding=UTF_8))
        raw["approved"] = True
        raw["approved_at"] = datetime.now(UTC).isoformat()
        path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding=UTF_8)
        log.debug("Stamped %s as approved", path.name)
    except FileNotFoundError:
        log.warning("stamp_approved: artifact not found at %s -- skipping", path)
    except Exception:
        log.warning("stamp_approved: could not stamp %s -- continuing", path, exc_info=True)
