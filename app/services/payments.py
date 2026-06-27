"""Payment confirmation seam.

Today payment is confirmed manually by an admin (provider="manual"). When a real
processor is added later, its webhook (e.g. Stripe checkout.session.completed)
should resolve the Invoice and call `confirm_paid` — the single place that flips
an invoice to paid — so the rest of the app is provider-agnostic.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.invoice import Invoice


def confirm_paid(db: Session, invoice: Invoice, *, admin_id: Optional[UUID] = None) -> Invoice:
    """Mark an invoice paid. Idempotent: a paid invoice is returned unchanged."""
    if invoice.status == "paid":
        return invoice
    invoice.status = "paid"
    invoice.paid_at = datetime.now(timezone.utc)
    invoice.paid_by_admin_id = admin_id
    return invoice
