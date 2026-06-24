import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.limiter import limiter
from app.routers import auth as auth_router, chat as chat_router, properties as properties_router, conversations as conversations_router, admin_properties as admin_properties_router, admin_users as admin_users_router, sellers as sellers_router, sitemap as sitemap_router
from app.services.digest_service import run_listing_digests

logger = logging.getLogger(__name__)

# Daily listing-digest run time. A plain in-process loop rather than an
# external cron — no extra infra to run this app anywhere, and double
# firing across replicas isn't a concern at this project's scale.
DIGEST_HOUR_UTC = 9


def _seconds_until_next_digest_run() -> float:
    now = datetime.now(timezone.utc)
    run_at = now.replace(hour=DIGEST_HOUR_UTC, minute=0, second=0, microsecond=0)
    if run_at <= now:
        run_at += timedelta(days=1)
    return (run_at - now).total_seconds()


async def _digest_loop():
    while True:
        await asyncio.sleep(_seconds_until_next_digest_run())
        try:
            with SessionLocal() as db:
                run_listing_digests(db)
        except Exception:
            logger.exception("Listing digest run failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_digest_loop())
    logger.info("Digest scheduler started (next run in %.0fs)", _seconds_until_next_digest_run())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="DarSyria API",
    description="Backend for the DarSyria real estate platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(chat_router.router)
app.include_router(properties_router.router)
app.include_router(conversations_router.router)
app.include_router(admin_properties_router.router)
app.include_router(admin_users_router.router)
app.include_router(sellers_router.router)
app.include_router(sitemap_router.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "darsyria-api"}


@app.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    """Verify the database is reachable and the schema is initialized."""
    result = db.execute(text("SELECT 1")).scalar()
    pgvector = db.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    users_table = db.execute(
        text("SELECT to_regclass('public.users')")
    ).scalar()
    return {
        "database": "connected" if result == 1 else "error",
        "pgvector_installed": pgvector == "vector",
        "users_table_exists": users_table == "users",
    }


@app.get("/")
def root():
    return {"message": "DarSyria API. See /docs for documentation."}
