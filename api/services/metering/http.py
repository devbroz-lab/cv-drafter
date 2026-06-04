"""HTTP helpers for metering errors."""

from fastapi import HTTPException, status

from api.services.metering.service import InsufficientCreditsError


def raise_insufficient_credits(exc: InsufficientCreditsError) -> None:
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "message": "Insufficient credits",
            "required_credits": str(exc.required),
            "available_credits": str(exc.available),
            "event": exc.event,
        },
    ) from exc
