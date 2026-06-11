"""Login/signup email allowlist."""

from __future__ import annotations

from fastapi import HTTPException, status

from api.config import settings

# Default closed beta — override or extend via AUTH_EMAIL_ALLOWLIST in .env
_DEFAULT_ALLOWED_EMAILS = frozenset(
    {
        "b.hamid0210@gmail.com",
        "alias.wardakmd@gmail.com",
        "daksh.suryavanshi2003@gmail.com",
        "dakshsuryavanshi2003@gmail.com",
        "dakshrachit11@gmail.com",
        "qamarali9584@gmail.com",
        "yashs9131@gmail.com",
        "mohdazam0453@gmail.com",
        "stefan.salow@gfa-group.de",
    }
)

ACCESS_DENIED_DETAIL = (
    "Access is restricted. This email is not authorized to use Tailor-it."
)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def allowed_emails() -> frozenset[str]:
    raw = (settings.auth_email_allowlist or "").strip()
    if not raw:
        return _DEFAULT_ALLOWED_EMAILS
    parsed = {normalize_email(part) for part in raw.split(",") if part.strip()}
    return frozenset(parsed) if parsed else _DEFAULT_ALLOWED_EMAILS


def is_email_allowed(email: str) -> bool:
    return normalize_email(email) in allowed_emails()


def require_allowed_email(email: str) -> None:
    if not is_email_allowed(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ACCESS_DENIED_DETAIL,
        )
