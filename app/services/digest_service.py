import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.follow import Follow
from app.models.property import Property
from app.models.saved_search import SavedSearch
from app.models.user import User
from app.services.email_service import EmailError, send_daily_update
from app.services.property_filters import apply_property_filters
from app.services.seller_helpers import seller_display_name

logger = logging.getLogger(__name__)

# Per-section cap on listings rendered inline; the rest become "+N more".
# Every new listing still advances the watermark — the cap only affects
# what's shown.
MAX_LISTINGS_PER_SECTION = 10


def _format_price(amount, currency: str) -> str:
    try:
        return f"{amount:,.0f} {currency}"
    except (TypeError, ValueError):
        return f"{amount} {currency}"


def _listing_entry(p: Property, locale: str) -> dict:
    return {
        "title": p.title,
        "url": f"{settings.frontend_url}/{locale}/properties/{p.id}",
        "location": f"{p.neighborhood}, {p.city}" if p.neighborhood else p.city,
        "price": _format_price(p.price_amount, p.price_currency),
    }


def run_daily_updates(db: Session) -> int:
    """
    Send one combined daily-update email per user, merging:
      (a) new listings from sellers they follow, and
      (b) new matches for their saved searches.

    "New" is published_at > the relevant watermark (Follow.last_digest_at or
    SavedSearch.last_alerted_at, falling back to the row's created_at). The
    watermarks advance only after a successful send, so a failed email is
    retried next run. Safe to call repeatedly; returns the number of emails
    sent. Runs daily via the scheduler in main.py but is plain and
    script-testable on its own.
    """
    follower_ids = db.execute(select(Follow.follower_id).distinct()).scalars().all()
    searcher_ids = db.execute(select(SavedSearch.user_id).distinct()).scalars().all()
    user_ids = set(follower_ids) | set(searcher_ids)

    sent = 0
    for user_id in user_ids:
        user = db.get(User, user_id)
        if not user or user.deleted_at is not None:
            continue
        locale = user.locale if user.locale in ("en", "de", "ar") else "en"

        follow_sections: list[dict] = []
        touched_follows: list[Follow] = []
        search_sections: list[dict] = []
        touched_searches: list[SavedSearch] = []

        # (a) New listings from followed sellers.
        follows = db.execute(
            select(Follow).where(Follow.follower_id == user_id)
        ).scalars().all()
        for follow in follows:
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
            follow_sections.append({
                "label": seller_display_name(owner) or owner.email.split("@")[0],
                "listings": [_listing_entry(p, locale) for p in shown],
                "more_count": len(new_listings) - len(shown),
            })
            touched_follows.append(follow)

        # (b) New listings matching saved searches.
        searches = db.execute(
            select(SavedSearch).where(SavedSearch.user_id == user_id)
        ).scalars().all()
        for ss in searches:
            watermark = ss.last_alerted_at or ss.created_at
            stmt = select(Property).join(User, Property.owner_id == User.id)
            stmt = apply_property_filters(
                stmt,
                city=ss.city,
                property_type=ss.property_type,
                min_price=ss.min_price,
                max_price=ss.max_price,
                rooms=ss.rooms,
                seller=ss.seller,
            )
            stmt = stmt.where(
                Property.published_at.isnot(None),
                Property.published_at > watermark,
            ).order_by(Property.published_at.desc())
            matches = db.execute(stmt).scalars().all()
            if not matches:
                continue
            shown = matches[:MAX_LISTINGS_PER_SECTION]
            search_sections.append({
                "label": ss.label,
                "listings": [_listing_entry(p, locale) for p in shown],
                "more_count": len(matches) - len(shown),
            })
            touched_searches.append(ss)

        if not follow_sections and not search_sections:
            continue

        try:
            send_daily_update(
                to_email=user.email,
                follow_sections=follow_sections,
                search_sections=search_sections,
                locale=locale,
            )
        except EmailError:
            logger.exception("Daily update failed for user %s — will retry next run", user_id)
            continue

        now = datetime.now(timezone.utc)
        for follow in touched_follows:
            follow.last_digest_at = now
        for ss in touched_searches:
            ss.last_alerted_at = now
        db.commit()
        sent += 1

    logger.info("Daily update run complete: %d email(s) sent", sent)
    return sent
