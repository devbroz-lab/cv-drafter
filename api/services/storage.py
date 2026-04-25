"""Supabase Storage helpers (upload + signed download URLs)."""

from __future__ import annotations

import os
from typing import Any

from api.config import settings
from api.services.database import get_service_client


def _unwrap_response(result: Any) -> Any:
    """Normalize supabase-py responses that may be plain dicts or `{data, error}` wrappers."""
    if result is None:
        return None
    err = getattr(result, "error", None)
    if err:
        raise RuntimeError(str(err))
    if hasattr(result, "data"):
        return result.data
    return result


def _bucket() -> str:
    if not settings.supabase_storage_bucket:
        raise RuntimeError("SUPABASE_STORAGE_BUCKET is not set in environment")
    return settings.supabase_storage_bucket


def _storage() -> Any:
    return get_service_client().storage.from_(_bucket())


def build_object_path(session_id: str, kind: str, original_filename: str) -> str:
    """Return object key inside the bucket: ``{session_id}/{kind}/{safe_basename}``."""
    base = os.path.basename(original_filename or "upload.bin") or "upload.bin"
    # avoid odd characters breaking keys — keep simple alnum-ish
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)[:200]
    return f"{session_id}/{kind}/{safe}"


def upload_bytes(
    *,
    object_path: str,
    data: bytes,
    content_type: str | None,
) -> None:
    opts: dict[str, Any] = {"upsert": "true"}
    if content_type:
        opts["content-type"] = content_type
    raw = _storage().upload(object_path, data, file_options=opts)
    _unwrap_response(raw)


def download_bytes(object_path: str) -> bytes:
    raw = _storage().download(object_path)
    result = _unwrap_response(raw)
    if not isinstance(result, bytes | bytearray):
        raise RuntimeError(f"Unexpected download response: {type(result)!r}")
    return bytes(result)


def create_signed_download_url(*, object_path: str, expires_in: int) -> str:
    if expires_in < 60 or expires_in > 60 * 60 * 24 * 7:
        raise ValueError("expires_in must be between 60 and 604800 seconds")
    raw = _storage().create_signed_url(object_path, expires_in)
    result = _unwrap_response(raw)
    if isinstance(result, dict):
        url = result.get("signedURL") or result.get("signedUrl") or result.get("signed_url")
        if url:
            return str(url)
    for attr in ("signed_url", "signedURL", "signedUrl"):
        if hasattr(result, attr):
            val = getattr(result, attr)
            if val:
                return str(val)
    raise RuntimeError(f"Unexpected signed URL response: {result!r}")
