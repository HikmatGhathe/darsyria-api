"""Error monitoring wiring (Sentry).

Centralizes Sentry setup so `main.py` stays uncluttered. The whole thing is a
no-op unless ``SENTRY_DSN`` is configured, so local and CI runs are unaffected.

When enabled, sentry-sdk auto-instruments FastAPI/Starlette (request errors,
transactions) and the logging integration captures ``ERROR``-level logs as
events — which includes the digest loop's ``logger.exception`` calls.
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def init_sentry() -> None:
    if not settings.sentry_dsn:
        logger.info("Sentry disabled (no SENTRY_DSN set).")
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        release=f"darsyria-api@{_app_version()}",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # Don't ship request bodies / cookies / user IPs to Sentry — this app
        # handles PII and auth cookies. Errors carry stack traces, not payloads.
        send_default_pii=False,
    )
    logger.info("Sentry initialized (environment=%s).", settings.app_env)


def _app_version() -> str:
    # Kept in step with the FastAPI app version; cheap to read here without a
    # circular import on `app`.
    return "0.1.0"
