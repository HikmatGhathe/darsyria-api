import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user
from app.models.invoice import Invoice
from app.models.user import User
from app.schemas.billing import BillingConfig, InvoiceOut
from app.services import settings_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/config", response_model=BillingConfig)
def billing_config(db: Session = Depends(get_db), _: User = Depends(get_optional_user)):
    """Whether listings currently require payment + the price, for the publish UI."""
    amount, currency = settings_service.listing_price(db)
    return BillingConfig(
        payment_required=settings_service.get_bool(db, settings_service.PAYMENT_REQUIRED),
        price_amount=amount,
        price_currency=currency,
    )


@router.get("/invoices", response_model=list[InvoiceOut])
def my_invoices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The caller's own invoices, newest first."""
    invoices = db.execute(
        select(Invoice)
        .where(Invoice.user_id == current_user.id)
        .order_by(Invoice.created_at.desc())
    ).scalars().all()
    return invoices
