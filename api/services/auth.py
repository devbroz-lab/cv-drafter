"""Application auth helpers and FastAPI dependency."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

import bcrypt
import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token as google_id_token

from api.config import settings
from api.services.database import (
    create_app_user,
    delete_refresh_token,
    find_valid_refresh_token,
    get_app_user_by_email,
    get_app_user_by_id,
    get_service_client,
    save_refresh_token,
    update_app_user,
)

_bearer = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class AuthenticatedUser:
    user_id: str
    email: str | None = None
    auth_provider: str = "app"


def _jwt_secret() -> str:
    secret = settings.jwt_secret or settings.api_secret_key
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT secret is not configured",
        )
    return secret


def _jwt_refresh_secret() -> str:
    return settings.jwt_refresh_secret or _jwt_secret()


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_access_token(user_id: str, email: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def generate_refresh_token(user_id: str) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.refresh_token_expires_days)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, _jwt_refresh_secret(), algorithm="HS256"), expires_at


def verify_access_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Invalid access token type")
    return payload


def verify_refresh_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, _jwt_refresh_secret(), algorithms=["HS256"])
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Invalid refresh token type")
    return payload


def _issue_user_tokens(user: dict[str, Any]) -> dict[str, Any]:
    access_token = generate_access_token(str(user["id"]), str(user["email"]))
    refresh_token, refresh_expires_at = generate_refresh_token(str(user["id"]))
    save_refresh_token(
        user_id=str(user["id"]),
        token=refresh_token,
        expires_at_iso=refresh_expires_at.isoformat(),
    )
    return {
        "user": {"id": str(user["id"]), "email": str(user["email"])},
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


def register_with_email(email: str, password: str) -> dict[str, Any]:
    existing = get_app_user_by_email(email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already in use",
        )
    user = create_app_user(
        email=email,
        password_hash=hash_password(password),
        google_id=None,
    )
    return _issue_user_tokens(user)


def login_with_email(email: str, password: str) -> dict[str, Any]:
    user = get_app_user_by_email(email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    password_hash = user.get("password_hash")
    if not password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account uses social login",
        )
    if not verify_password(password, str(password_hash)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return _issue_user_tokens(user)


def login_with_google(id_token: str) -> dict[str, Any]:
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GOOGLE_CLIENT_ID is not configured",
        )
    try:
        payload = google_id_token.verify_oauth2_token(
            id_token,
            GoogleRequest(),
            settings.google_client_id,
        )
    except Exception as exc:
        logger.warning("Google ID token verification failed: %s", exc, exc_info=settings.debug)
        detail = (
            f"Invalid Google token: {exc}"
            if settings.debug
            else "Invalid Google token"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        ) from exc

    email = str(payload.get("email") or "").lower()
    google_id = str(payload.get("sub") or "")
    if not email or not google_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account is missing required fields",
        )

    user = get_app_user_by_email(email)
    if not user:
        user = create_app_user(email=email, password_hash=None, google_id=google_id)
    elif not user.get("google_id"):
        user = update_app_user(str(user["id"]), {"google_id": google_id}) or user
    return _issue_user_tokens(user)


def login_with_microsoft(id_token: str) -> dict[str, Any]:
    if not settings.microsoft_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MICROSOFT_CLIENT_ID is not configured",
        )

    try:
        jwks = PyJWKClient("https://login.microsoftonline.com/common/discovery/v2.0/keys")
        signing_key = jwks.get_signing_key_from_jwt(id_token)
        payload = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.microsoft_client_id,
            options={"verify_iss": False},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Microsoft token",
        ) from exc

    email = str(
        payload.get("email")
        or payload.get("preferred_username")
        or payload.get("upn")
        or ""
    ).lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Microsoft account is missing required fields",
        )

    user = get_app_user_by_email(email)
    if not user:
        user = create_app_user(email=email, password_hash=None, google_id=None)
    return _issue_user_tokens(user)


def refresh_access(refresh_token: str) -> str:
    try:
        payload = verify_refresh_token(refresh_token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc
    record = find_valid_refresh_token(refresh_token)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked or expired",
        )
    user = get_app_user_by_id(str(payload["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return generate_access_token(str(user["id"]), str(user["email"]))


def logout_refresh_token(refresh_token: str) -> None:
    delete_refresh_token(refresh_token)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        app_payload = verify_access_token(token)
        return AuthenticatedUser(
            user_id=str(app_payload["sub"]),
            email=str(app_payload.get("email") or ""),
            auth_provider="app",
        )
    except Exception:
        # Backward compatibility path: still accept Supabase access tokens
        # so live clients are not broken while auth migration is in progress.
        pass

    try:
        response = get_service_client().auth.get_user(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = getattr(response, "user", None)
    user_id = getattr(user, "id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthenticatedUser(
        user_id=str(user_id),
        email=getattr(user, "email", None),
        auth_provider="supabase",
    )
