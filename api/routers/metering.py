"""Metering API — balance and usage ledger."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.services.auth import AuthenticatedUser, get_current_user
from api.services.metering import (
    get_balance,
    get_rates,
    list_ledger,
    provision_new_user,
)

router = APIRouter(prefix="/metering", tags=["metering"])
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


class MeterRatesResponse(BaseModel):
    credit_usd: float
    pipeline_run_usd: float
    revision_usd: float
    initial_grant_credits: float
    pipeline_run_credits: str
    revision_credits: str


class BalanceResponse(BaseModel):
    available_credits: str
    reserved_credits: str
    total_credits: str
    rates: MeterRatesResponse


class LedgerEntryResponse(BaseModel):
    id: str
    session_id: str | None = None
    event_type: str
    amount_credits: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class LedgerListResponse(BaseModel):
    entries: list[LedgerEntryResponse]


@router.get("/balance", response_model=BalanceResponse)
async def metering_balance(current_user: CurrentUser) -> BalanceResponse:
    provision_new_user(current_user.user_id)
    balance = get_balance(current_user.user_id)
    rates = get_rates()
    return BalanceResponse(
        available_credits=str(balance.available_credits),
        reserved_credits=str(balance.reserved_credits),
        total_credits=str(balance.total_credits),
        rates=MeterRatesResponse(**rates),
    )


@router.get("/ledger", response_model=LedgerListResponse)
async def metering_ledger(
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=100),
) -> LedgerListResponse:
    provision_new_user(current_user.user_id)
    rows = list_ledger(current_user.user_id, limit=limit)
    entries = [
        LedgerEntryResponse(
            id=str(row["id"]),
            session_id=str(row["session_id"]) if row.get("session_id") else None,
            event_type=str(row["event_type"]),
            amount_credits=str(row["amount_credits"]),
            metadata=dict(row.get("metadata") or {}),
            created_at=str(row["created_at"]),
        )
        for row in rows
    ]
    return LedgerListResponse(entries=entries)
