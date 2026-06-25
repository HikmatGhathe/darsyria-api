from typing import Optional

from app.models.property import Property
from app.models.user import User


def apply_property_filters(
    stmt,
    *,
    governorate: Optional[str] = None,
    city: Optional[str] = None,
    property_type: Optional[str] = None,
    min_price=None,
    max_price=None,
    rooms: Optional[int] = None,
    seller: Optional[str] = None,
):
    """
    Apply the shared 'active listing' filter clauses to a statement. The
    statement must already join User (the seller filter references User
    columns). Used by the browse list/count endpoints and by saved-search
    matching in the daily digest.
    """
    stmt = stmt.where(Property.status == "active")
    if governorate:
        stmt = stmt.where(Property.governorate == governorate)
    if city:
        stmt = stmt.where(Property.city.ilike(f"%{city}%"))
    if property_type:
        stmt = stmt.where(Property.property_type == property_type)
    if min_price is not None:
        stmt = stmt.where(Property.price_amount >= min_price)
    if max_price is not None:
        stmt = stmt.where(Property.price_amount <= max_price)
    if rooms is not None:
        stmt = stmt.where(Property.rooms == rooms)
    if seller:
        like = f"%{seller}%"
        stmt = stmt.where(
            (User.company_name.ilike(like)) | (User.full_name.ilike(like))
        )
    return stmt
