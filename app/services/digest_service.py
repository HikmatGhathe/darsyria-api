import logging
from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.follow import Follow
from app.models.property import Property
from app.models.user import User
from app.services.email_service import EmailError, send_new_listings_digest
from app.services.seller_helpers import seller_display_name

logger = logging.getLogger(__name__)

# Per-seller cap on how many listings are rendered inline in one digest
# email; the rest are summarized as "+N more". A company posting many
# listings in a day should not blow up the email, but every new listing
# still advances the watermark (the cap only affects what's *shown*).
MAX_LISTINGS_PER_SECTION = 10


def _format_price(amount, currency: str) -> str:
    try:
        return f"{amount:,.0f} {currency}"
    except (TypeError, ValueError):
        return f"{amount} {currency}"


def run_listing_digests(db: Session) -> int:
    """
    Send one digest email per follower covering every new listing across
    everyone they follow (grouped by seller), then advance the per-follow
    watermark. Safe to call repeatedly — a follower with nothing new since
    their last digest gets no email and nothing is changed for them.

    Meant to run once a day via the scheduler in main.py, but is plain,
    synchronous, and curl/script-testable on its own.

    Returns the number of emails sent.
    """
    follows = db.execute(
        select(Follow)
        .join(User, Follow.follower_id == User.id)
        .where(User.deleted_at.is_(None))
    ).scalars().all()

    by_follower: dict[UUID, list[Follow]] = defaultdict(list)
    for follow in follows:
        by_follower[follow.follower_id].append(follow)

    sent = 0
    for follower_id, follower_follows in by_follower.items():
        follower = db.get(User, follower_id)
        if not follower or follower.deleted_at is not None:
            continue

        locale = follower.locale if follower.locale in ("en", "de", "ar") else "en"

        sections = []
        touched_follows = []

        for follow in follower_follows:
            watermark = follow.last_digest_at or follow.created_at
            new_listings = db.execute(
                select(Property)
                .where(
                    Property.owner_id == follow.followed_user_id,
                    Property.status == "active",
                    Property.published_at.isnot(None),
                    Property.published_at > watermark,
                )
                .order_by(Property.published_at.desc())
            ).scalars().all()

            if not new_listings:
                continue

            owner = db.get(User, follow.followed_user_id)
            if not owner or owner.deleted_at is not None:
                continue

            shown = new_listings[:MAX_LISTINGS_PER_SECTION]
            sections.append({
                "seller_name": seller_display_name(owner) or owner.email.split("@")[0],
                "listings": [
                    {
                        "title": p.title,
                        "url": f"{settings.frontend_url}/{locale}/properties/{p.id}",
                        "location": f"{p.neighborhood}, {p.city}" if p.neighborhood else p.city,
                        "price": _format_price(p.price_amount, p.price_currency),
                    }
                    for p in shown
                ],
                "more_count": len(new_listings) - len(shown),
            })
            touched_follows.append(follow)

        if not sections:
            continue

        try:
            send_new_listings_digest(to_email=follower.email, sections=sections, locale=locale)
        except EmailError:
            logger.exception("Digest email failed for follower %s — will retry next run", follower_id)
            continue

        now = datetime.now(timezone.utc)
        for follow in touched_follows:
            follow.last_digest_at = now
        db.commit()
        sent += 1

    logger.info("Listing digest run complete: %d email(s) sent", sent)
    return sent
