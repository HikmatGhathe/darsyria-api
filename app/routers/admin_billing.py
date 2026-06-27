"""Admin billing: the free-mode/price settings and the invoice queue.
All routes require an admin (is_admin=True).
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.invoice import Invoice
from app.models.property import Property
from app.models.user import User
from app.schemas.billing import AdminInvoiceItem, BillingConfig, BillingSettingsUpdate
from app.services import settings_service
from app.services.payments import confirm_paid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/billing", tags=["admin-billing"])


@router.get("/settings", response_model=BillingConfig)
def get_billing_settings(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    amount, currency = settings_service.listing_price(db)
    return BillingConfig(
        payment_required=settings_service.get_bool(db, settings_service.PAYMENT_REQUIRED),
        price_amount=amount,
        price_currency=currency,
    )


@router.put("/settings", response_model=BillingConfig)
def update_billing_settings(
    payload: BillingSettingsUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Toggle the payment requirement (free mode) and set the listing price."""
    if payload.payment_required is not None:
        settings_service.set_setting(
            db, settings_service.PAYMENT_REQUIRED, "true" if payload.payment_required else "false"
        )
    if payload.price_amount is not None:
        settings_service.set_setting(
            db, settings_service.LISTING_PRICE_AMOUNT, str(payload.price_amount)
        )
    if payload.price_currency is not None:
        settings_service.set_setting(
            db, settings_service.LISTING_PRICE_CURRENCY, payload.price_currency
        )
    db.commit()
    logger.info("Admin %s updated billing settings", admin.id)

    amount, currency = settings_service.listing_price(db)
    return BillingConfig(
        payment_required=settings_service.get_bool(db, settings_service.PAYMENT_REQUIRED),
        price_amount=amount,
        price_currency=currency,
    )


@router.get("/invoices", response_model=list[AdminInvoiceItem])
def list_invoices(
    invoice_status: Optional[str] = Query(default=None, alias="status", max_length=20),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    stmt = select(Invoice).order_by(Invoice.created_at.desc())
    if invoice_status:
        stmt = stmt.where(Invoice.status == invoice_status)
    invoices = db.execute(stmt).scalars().all()

    items = []
    for inv in invoices:
        prop = db.get(Property, inv.property_id)
        owner = db.get(User, inv.user_id)
        items.append(
            AdminInvoiceItem(
                id=inv.id,
                property_id=inv.property_id,
                property_title=prop.title if prop else "",
                owner_id=inv.user_id,
                owner_email=owner.email if owner else "",
                amount=inv.amount,
                currency=inv.currency,
                status=inv.status,
                provider=inv.provider,
                created_at=inv.created_at,
                due_at=inv.due_at,
                paid_at=inv.paid_at,
            )
        )
    return items


def _get_invoice_or_404(db: Session, invoice_id: UUID) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return inv


@router.post("/invoices/{invoice_id}/mark-paid", response_model=AdminInvoiceItem)
def mark_invoice_paid(
    invoice_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    inv = _get_invoice_or_404(db, invoice_id)
    confirm_paid(db, inv, admin_id=admin.id)
    db.commit()
    db.refresh(inv)
    logger.info("Admin %s marked invoice %s paid", admin.id, invoice_id)
    return _to_admin_item(db, inv)


@router.post("/invoices/{invoice_id}/void", response_model=AdminInvoiceItem)
def void_invoice(
    invoice_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    inv = _get_invoice_or_404(db, invoice_id)
    inv.status = "void"
    db.commit()
    db.refresh(inv)
    logger.info("Admin %s voided invoice %s", admin.id, invoice_id)
    return _to_admin_item(db, inv)


def _to_admin_item(db: Session, inv: Invoice) -> AdminInvoiceItem:
    prop = db.get(Property, inv.property_id)
    owner = db.get(User, inv.user_id)
    return AdminInvoiceItem(
        id=inv.id,
        property_id=inv.property_id,
        property_title=prop.title if prop else "",
        owner_id=inv.user_id,
        owner_email=owner.email if owner else "",
        amount=inv.amount,
        currency=inv.currency,
        status=inv.status,
        provider=inv.provider,
        created_at=inv.created_at,
        due_at=inv.due_at,
        paid_at=inv.paid_at,
    )
