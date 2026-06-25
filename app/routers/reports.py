import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.limiter import limiter
from app.models.property import Property
from app.models.report import Report
from app.models.user import User
from app.schemas.report import ReportCreate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/hour")
def create_report(
    payload: ReportCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Report a suspicious listing or seller. One open report per (reporter,
    target) — re-reporting is a no-op. A reported listing is also auto-flagged
    into the existing admin moderation queue. Never auto-hides anything.
    """
    if payload.property_id is not None:
        prop = db.get(Property, payload.property_id)
        if not prop:
            raise HTTPException(status_code=404, detail="Listing not found")
        if prop.owner_id == current_user.id:
            raise HTTPException(status_code=400, detail="You can't report your own listing")
        dedup = Report.property_id == payload.property_id
    else:
        target = db.get(User, payload.reported_user_id)
        if not target or target.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Seller not found")
        if target.id == current_user.id:
            raise HTTPException(status_code=400, detail="You can't report yourself")
        dedup = Report.reported_user_id == payload.reported_user_id

    # One open report per reporter per target — re-reporting is idempotent.
    existing = db.execute(
        select(Report).where(
            Report.reporter_id == current_user.id,
            Report.status == "open",
            dedup,
        )
    ).scalar_one_or_none()
    if existing:
        return None

    report = Report(
        reporter_id=current_user.id,
        property_id=payload.property_id,
        reported_user_id=payload.reported_user_id,
        reason=payload.reason,
        details=payload.details,
    )
    db.add(report)

    # Auto-flag the reported listing so it also surfaces in the existing
    # admin flagged queue.
    if payload.property_id is not None and prop.flagged_at is None:
        prop.flagged_at = datetime.now(timezone.utc)

    db.commit()
    logger.info(
        "User %s reported %s (%s)",
        current_user.id,
        f"listing {payload.property_id}" if payload.property_id else f"seller {payload.reported_user_id}",
        payload.reason,
    )
    return None
