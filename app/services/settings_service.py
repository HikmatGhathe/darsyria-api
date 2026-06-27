"""Read/write admin-tunable runtime settings (the app_settings table).

Centralizes the keys and their defaults so callers don't hardcode strings.
Everything is stored as text; helpers coerce.
"""
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting

# Keys + defaults (used when the row is absent).
PAYMENT_REQUIRED = "payment_required"
LISTING_PRICE_AMOUNT = "listing_price_amount"
LISTING_PRICE_CURRENCY = "listing_price_currency"

DEFAULTS = {
    PAYMENT_REQUIRED: "false",
    LISTING_PRICE_AMOUNT: "10",
    LISTING_PRICE_CURRENCY: "USD",
}


def get_setting(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key, "")


def get_bool(db: Session, key: str) -> bool:
    return get_setting(db, key).strip().lower() in ("true", "1", "yes", "on")


def get_decimal(db: Session, key: str, fallback: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(get_setting(db, key))
    except (InvalidOperation, ValueError):
        return fallback


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value


def listing_price(db: Session) -> tuple[Decimal, str]:
    """Current listing price as (amount, currency)."""
    amount = get_decimal(db, LISTING_PRICE_AMOUNT, Decimal("10"))
    currency = get_setting(db, LISTING_PRICE_CURRENCY) or "USD"
    return amount, currency
