"""Tier registry — code-owned, mirroring ProviderRegistry's philosophy.

Free has no entry here and no Stripe object: it is simply the absence of
a subscriptions row (app/models/subscription.py). Every paid tier maps
to a Stripe Price ID sourced from settings — never a hardcoded dollar
amount anywhere in this codebase. See architecture.md §8b.
"""

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class TierMetadata:
    tier_id: str
    display_name: str
    stripe_price_id: str


class UnknownTierError(Exception):
    pass


def _build_tiers() -> dict[str, TierMetadata]:
    return {
        "pro": TierMetadata(
            tier_id="pro", display_name="Pro", stripe_price_id=settings.stripe_price_id_pro
        ),
        "enterprise": TierMetadata(
            tier_id="enterprise",
            display_name="Enterprise",
            stripe_price_id=settings.stripe_price_id_enterprise,
        ),
    }


TIERS: dict[str, TierMetadata] = _build_tiers()


def get_tier(tier_id: str) -> TierMetadata:
    tier = TIERS.get(tier_id)
    if tier is None:
        raise UnknownTierError(tier_id)
    return tier
