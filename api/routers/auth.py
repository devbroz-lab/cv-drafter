"""App auth endpoints (email/password + Google OAuth token login)."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from api.services.auth import (
    AuthenticatedUser,
    get_current_user,
    login_with_email,
    login_with_google,
    login_with_microsoft,
    logout_refresh_token,
    refresh_access,
    register_with_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=256)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(min_length=1, alias="idToken")


class MicrosoftLoginRequest(BaseModel):
    id_token: str = Field(min_length=1, alias="idToken")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, alias="refreshToken")


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1, alias="refreshToken")


class AuthUserResponse(BaseModel):
    id: str
    email: str


class AuthResponse(BaseModel):
    user: AuthUserResponse
    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")


class RefreshResponse(BaseModel):
    access_token: str = Field(alias="accessToken")


class MessageResponse(BaseModel):
    message: str


class MeResponse(BaseModel):
    user: AuthUserResponse


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest) -> AuthResponse:
    result = register_with_email(payload.email, payload.password)
    return AuthResponse(
        user=AuthUserResponse(**result["user"]),
        accessToken=result["access_token"],
        refreshToken=result["refresh_token"],
    )


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest) -> AuthResponse:
    result = login_with_email(payload.email, payload.password)
    return AuthResponse(
        user=AuthUserResponse(**result["user"]),
        accessToken=result["access_token"],
        refreshToken=result["refresh_token"],
    )


@router.post("/google", response_model=AuthResponse)
async def google_login(payload: GoogleLoginRequest) -> AuthResponse:
    result = login_with_google(payload.id_token)
    return AuthResponse(
        user=AuthUserResponse(**result["user"]),
        accessToken=result["access_token"],
        refreshToken=result["refresh_token"],
    )


@router.post("/microsoft", response_model=AuthResponse)
async def microsoft_login(payload: MicrosoftLoginRequest) -> AuthResponse:
    result = login_with_microsoft(payload.id_token)
    return AuthResponse(
        user=AuthUserResponse(**result["user"]),
        accessToken=result["access_token"],
        refreshToken=result["refresh_token"],
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(payload: RefreshRequest) -> RefreshResponse:
    access_token = refresh_access(payload.refresh_token)
    return RefreshResponse(accessToken=access_token)


@router.post("/logout", response_model=MessageResponse)
async def logout(payload: LogoutRequest) -> MessageResponse:
    logout_refresh_token(payload.refresh_token)
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=MeResponse)
async def me(current_user: AuthenticatedUser = Depends(get_current_user)) -> MeResponse:  # noqa: B008
    if not current_user.email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return MeResponse(user=AuthUserResponse(id=current_user.user_id, email=current_user.email))
