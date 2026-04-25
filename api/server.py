"""FastAPI application entrypoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env into os.environ BEFORE any module that reads environment variables
# (e.g. Anthropic SDK reads ANTHROPIC_API_KEY from os.environ at client init).
load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from api.config import settings  # noqa: E402
from api.routers import health, sessions  # noqa: E402

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """
    Run startup tasks before the server begins accepting requests, then tear
    down cleanly on shutdown.

    Startup
    -------
    - Reset any sessions stuck in 'processing' to 'failed'.  These are ghost
      sessions left over from a crash or redeploy that interrupted a background
      task mid-flight.  Without this, they would hang in 'processing' forever.
    """
    # Import here to avoid circular imports at module load time.
    from api.services.database import reset_stale_processing_sessions

    try:
        reset_stale_processing_sessions()
    except Exception:
        # Do not prevent startup if the DB is temporarily unreachable.
        log.exception("Startup recovery query failed — stale sessions were not reset")

    yield
    # Shutdown hook (nothing to tear down yet).


app = FastAPI(
    title="CV Reformatter API",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Set CORS_ORIGINS in .env to lock down specific frontend domains before going
# live.  During local development the default "*" is fine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(sessions.router)
