"""
Admin endpoints for the user-report queue. All routes require an admin.
Prefix: /admin/reports
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.property import Property
from app.models.report import Report
from app.models.user import User
from app.schemas.report import ReportAdminItem
from app.services.seller_helpers import seller_display_name

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/reports", tags=["admin-reports"])


def _enrich(db: Session, report: Report) -> ReportAdminItem:
    reporter = db.get(User, report.reporter_id)
    if report.property_id is not None:
        prop = db.get(Property, report.property_id)
        target_type = "listing"
        target_id = report.property_id
        target_label = prop.title if prop else None
        target_owner_id = prop.owner_id if prop else None
    else:
        seller = db.get(User, report.reported_user_id)
        target_type = "seller"
        target_id = report.reported_user_id
        target_label = seller_display_name(seller) if seller else None
        target_owner_id = report.reported_user_id
    return ReportAdminItem(
        id=report.id,
        reason=report.reason,
        details=report.details,
        status=report.status,
        created_at=report.created_at,
        reporter_email=reporter.email if reporter else None,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        target_owner_id=target_owner_id,
    )


@router.get("", response_model=list[ReportAdminItem])
def admin_list_reports(
    report_status: str = Query(default="open", alias="status", pattern="^(open|resolved|dismissed)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    reports = db.execute(
        select(Report)
        .where(Report.status == report_status)
        .order_by(Report.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).scalars().all()
    return [_enrich(db, r) for r in reports]


def _set_status(db: Session, report_id: UUID, admin: User, new_status: str) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    report.status = new_status
    report.reviewed_at = datetime.now(timezone.utc)
    report.reviewed_by = admin.id
    db.commit()
    db.refresh(report)
    logger.info("Admin %s marked report %s as %s", admin.id, report_id, new_status)
    return report


@router.post("/{report_id}/resolve", response_model=ReportAdminItem)
def admin_resolve_report(
    report_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    return _enrich(db, _set_status(db, report_id, admin, "resolved"))


@router.post("/{report_id}/dismiss", response_model=ReportAdminItem)
def admin_dismiss_report(
    report_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    return _enrich(db, _set_status(db, report_id, admin, "dismissed"))
